"""
Redis-backed fixed-window rate limiter for authentication endpoints.
Keyed on email+IP to block credential stuffing without hammering Postgres.
"""
import logging
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 10
_WINDOW_SECONDS = 300  # 5 minutes

# Atomic INCR + conditional EXPIRE — sets TTL only on the first increment
# so the window is fixed from the first attempt, not sliding.
_INCR_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


def _client_ip(request: Request) -> str:
    # Nginx forwards the real IP via X-Real-IP
    return request.headers.get("X-Real-IP") or request.client.host


async def check_auth_rate_limit(request: Request, email: str, endpoint: str) -> None:
    """
    Raise HTTP 429 if email+IP has exceeded 10 auth attempts in 5 minutes.
    Silently passes on Redis errors to avoid blocking logins during an outage.
    """
    from app.services.redis_client import get_redis

    ip = _client_ip(request)
    key = f"auth_rl:{endpoint}:{email.lower()}:{ip}"

    try:
        r = get_redis()
        count = int(await r.eval(_INCR_LUA, 1, key, _WINDOW_SECONDS))
        if count > _MAX_ATTEMPTS:
            ttl = await r.ttl(key)
            retry_after = str(max(ttl, 1))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many attempts. Try again in {retry_after} seconds.",
                headers={"Retry-After": retry_after},
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("auth rate limit check failed for %s — skipping", key)
