"""Module-level singleton Redis client. One pool per worker.

Hot paths (rate limiters, widget cache, idempotency gates, message tasks) used
to construct a fresh aioredis.from_url(...) per call and aclose() it. That
pattern paid DNS + TCP + AUTH + teardown overhead per request and walked
ephemeral ports into TIME_WAIT under sustained load. Calling get_redis()
returns a process-wide pooled client; never aclose() the result per call.

NOTE: app/services/redis_pubsub.py keeps its own long-lived client. It needs
a dedicated connection because pubsub.listen() blocks on the same socket for
the worker's lifetime — sharing it with normal Redis ops would deadlock.

NOTE: app/tasks/message_tasks.py uses settings.redis_queue_url (arq's queue),
which is a separate Redis URL/database from REDIS_URL. Do not migrate it here.
"""
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings


_client: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    """Return the process-wide Redis client. Lazily initialised on first call.

    The returned client owns its own ConnectionPool (max_connections=50). Do
    NOT aclose() it — that would tear down the pool for every other caller in
    this worker.
    """
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=50,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    """Close the singleton client. Called from main.py lifespan teardown."""
    global _client
    if _client is not None:
        client = _client
        _client = None
        try:
            await client.aclose()
        except Exception:
            pass
