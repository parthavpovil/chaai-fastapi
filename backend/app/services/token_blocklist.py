"""
Token Blocklist Service
Redis-backed JWT blocklist for logout support.

When a user logs out, the token's `jti` is stored in Redis with a TTL equal
to the token's remaining lifetime. Every authenticated request checks this
blocklist so blocked tokens are immediately invalidated.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Redis key prefix for blocked token JTIs
_KEY_PREFIX = "token_blocklist:"


def _key(jti: str) -> str:
    return f"{_KEY_PREFIX}{jti}"


async def _get_redis():
    """Return a Redis client using the app's REDIS_URL setting."""
    import redis.asyncio as aioredis
    from app.config import settings
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def block_token(jti: str, exp: int) -> None:
    """
    Add a token JTI to the blocklist.

    Args:
        jti: JWT ID claim from the token payload
        exp: JWT expiry timestamp (Unix epoch int) — used to set Redis TTL
    """
    try:
        expire_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
        ttl_seconds = int((expire_dt - datetime.now(timezone.utc)).total_seconds())
        if ttl_seconds <= 0:
            # Token already expired — no need to store
            return
        redis = await _get_redis()
        await redis.set(_key(jti), "1", ex=ttl_seconds)
        await redis.aclose()
    except Exception:
        logger.warning("Failed to add token to blocklist (jti=%s)", jti, exc_info=True)


async def is_blocked(jti: str) -> bool:
    """
    Check whether a token JTI has been blocklisted.

    Returns True if the token is blocked, False otherwise.
    On Redis errors returns False (fail-open) to avoid locking out users
    due to a transient Redis outage.
    """
    try:
        redis = await _get_redis()
        result = await redis.exists(_key(jti))
        await redis.aclose()
        return bool(result)
    except Exception:
        logger.warning("Token blocklist check failed (jti=%s) — allowing request", jti, exc_info=True)
        return False
