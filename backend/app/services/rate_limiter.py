"""
WebChat rate limiting — Redis sliding-window counter.

Replaced the original Postgres ARRAY implementation (appended a timestamp row
on every request, causing hot-row contention under load) with a Redis
INCR+EXPIRE fixed-window counter that is O(1) and lock-free.

The rate_limits DB table is now unused and will be dropped in a future migration.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

_WEBCHAT_MAX = 10
_WEBCHAT_WINDOW = 60  # seconds (1 minute)

# Atomic INCR + EXPIRE on first increment — same pattern used in auth_rate_limit.py
_INCR_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


class RateLimitExceededError(Exception):
    """Raised when a rate limit is exceeded."""
    pass


async def check_webchat_rate_limit(
    session_token: str,
    workspace_id: str,
    db=None,  # kept for backward compat — no longer used
) -> Dict[str, Any]:
    """
    Enforce the WebChat rate limit: 10 messages per 60 seconds per session.

    Raises RateLimitExceededError if the limit is exceeded.
    Silently passes on Redis errors to avoid blocking users during outages.
    """
    from app.services.redis_client import get_redis

    key = f"webchat_rl:{workspace_id}:{session_token}"
    try:
        r = get_redis()
        count = int(await r.eval(_INCR_LUA, 1, key, _WEBCHAT_WINDOW))
        if count > _WEBCHAT_MAX:
            ttl = await r.ttl(key)
            retry_after = max(ttl, 1)
            raise RateLimitExceededError(
                f"Rate limit exceeded: {_WEBCHAT_MAX} messages per minute. "
                f"Try again in {retry_after} seconds."
            )
        return {
            "allowed": True,
            "limit": _WEBCHAT_MAX,
            "remaining": max(_WEBCHAT_MAX - count, 0),
        }
    except RateLimitExceededError:
        raise
    except Exception:
        logger.warning("WebChat rate limit Redis check failed for %s — skipping", key)
        return {"allowed": True, "limit": _WEBCHAT_MAX, "remaining": _WEBCHAT_MAX}
