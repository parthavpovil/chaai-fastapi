"""
Widget cache — owns both L1 (in-process dict) and L2 (Redis) layers of the
get_webchat_channel_by_widget_id stack.

  L1: this module's _l1_widget_id_to_channel_id dict  ~ns hit, per-worker
  L2: Redis "widget:{widget_id}" key                  ~1ms hit, shared
  L3 (lives in webchat.py): indexed SELECT WHERE widget_id = $1

Why L2 exists despite L3 being fast: a freshly-booted gunicorn worker has
an empty L1, and the first request to that worker would otherwise pay one
Postgres round-trip. L2 (shared across workers) lets a sibling worker's
earlier lookup or the lifespan pre-warm satisfy the L1 cold miss with a
single Redis round-trip.

Invalidation is explicit — call invalidate_widget_cache(widget_id) after
a channel update that may have changed is_active or after a delete. The
single function clears BOTH L1 and L2.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_TTL = 300  # L2 Redis TTL, seconds
_L1_TTL = 60  # L1 in-process TTL, seconds — short so deactivations propagate

# L1: per-worker in-process dict. widget_id -> (channel_id, expires_at_monotonic).
# Module-level, so each gunicorn worker gets its own dict (Python state is
# per-process). Memory is ~80 bytes per entry — trivial at any realistic
# channel count.
_l1_widget_id_to_channel_id: dict = {}


def _l1_get(widget_id: str) -> Optional[str]:
    entry = _l1_widget_id_to_channel_id.get(widget_id)
    if not entry:
        return None
    channel_id, expires = entry
    if expires <= time.monotonic():
        _l1_widget_id_to_channel_id.pop(widget_id, None)
        return None
    return channel_id


def _l1_set(widget_id: str, channel_id: str) -> None:
    _l1_widget_id_to_channel_id[widget_id] = (
        str(channel_id),
        time.monotonic() + _L1_TTL,
    )


def _l1_invalidate(widget_id: str) -> None:
    _l1_widget_id_to_channel_id.pop(widget_id, None)


def _widget_key(widget_id: str) -> str:
    return f"widget:{widget_id}"


def _redis():
    """Process-wide pooled Redis client. Never aclose() per call."""
    from app.services.redis_client import get_redis
    return get_redis()


async def get_cached_channel_id(widget_id: str) -> Optional[str]:
    """L1 → L2 lookup. Returns channel_id, or None on miss.

    Checks L1 first (free). On L1 miss, hits Redis (~1ms). On L2 hit,
    populates L1 for subsequent calls in the same process.
    """
    cached = _l1_get(widget_id)
    if cached:
        return cached
    try:
        r = _redis()
        channel_id = await r.get(_widget_key(widget_id))
        if channel_id:
            _l1_set(widget_id, channel_id)
        return channel_id
    except Exception as exc:
        logger.debug("widget cache read error (widget_id=%s): %s", widget_id, exc)
        return None


async def set_cached_channel_id(widget_id: str, channel_id: str) -> None:
    """Populate both L1 and L2 with widget_id → channel_id."""
    _l1_set(widget_id, channel_id)
    try:
        r = _redis()
        await r.set(_widget_key(widget_id), str(channel_id), ex=_TTL)
    except Exception as exc:
        logger.debug("widget cache write error (widget_id=%s): %s", widget_id, exc)


async def invalidate_widget_cache(widget_id: Optional[str]) -> None:
    """Clear BOTH L1 and L2 for a widget. Safe to call with None (no-op).

    Called from the channel update / delete endpoints after commit so other
    workers see the change within their L1 TTL window. Note this only clears
    the L1 of THIS worker; other workers' L1 entries self-expire on the 60s
    L1 TTL or on the next deactivation-aware fetch.
    """
    if not widget_id:
        return
    _l1_invalidate(widget_id)
    try:
        r = _redis()
        await r.delete(_widget_key(widget_id))
    except Exception as exc:
        logger.debug("widget cache invalidation error (widget_id=%s): %s", widget_id, exc)


async def bulk_set_cached_channel_ids(mapping: dict) -> None:
    """Populate many widget_id → channel_id entries in BOTH L1 and L2.

    L1 fill is in-process and synchronous (just dict writes). L2 fill is
    a single Redis pipeline to amortize the network round-trip. Used by
    the lifespan pre-warm so worker startup doesn't make N Redis calls.
    Fails silently on Redis error; a partial pre-warm degrades to lazy
    warming via the normal get/set path.
    """
    if not mapping:
        return
    # L1 — local dict, never fails.
    for widget_id, channel_id in mapping.items():
        _l1_set(widget_id, channel_id)
    # L2 — Redis pipeline.
    try:
        r = _redis()
        async with r.pipeline(transaction=False) as pipe:
            for widget_id, channel_id in mapping.items():
                pipe.set(_widget_key(widget_id), str(channel_id), ex=_TTL)
            await pipe.execute()
    except Exception as exc:
        logger.debug("widget cache bulk write error (count=%d): %s", len(mapping), exc)
