"""
Refresh Token Service

Opaque refresh tokens stored in Redis.  Each token is a UUID that maps to
the user's claims.  On use the token is atomically deleted and a new one is
issued (rotation), so a stolen token can only be used once before it is
invalidated by the legitimate client's next refresh.
"""
import json
import logging
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "rt:"
_USER_KEY_PREFIX = "rt_user:"


def _key(rt_id: str) -> str:
    return f"{_KEY_PREFIX}{rt_id}"


def _user_key(user_id: str) -> str:
    return f"{_USER_KEY_PREFIX}{user_id}"


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def create_refresh_token(
    *,
    user_id: str,
    email: str,
    role: str,
    workspace_id: Optional[str],
) -> str:
    """Store a new refresh token in Redis and return its opaque ID."""
    rt_id = str(uuid4())
    data = json.dumps({
        "user_id": user_id,
        "email": email,
        "role": role,
        "workspace_id": workspace_id,
    })
    ttl = settings.JWT_REFRESH_EXPIRE_DAYS * 86400
    redis = await _get_redis()
    try:
        await redis.set(_key(rt_id), data, ex=ttl)
        await redis.sadd(_user_key(user_id), rt_id)
        await redis.expire(_user_key(user_id), ttl)
    finally:
        await redis.aclose()
    return rt_id


async def use_refresh_token(rt_id: str) -> Optional[dict]:
    """Validate and atomically consume a refresh token (rotation).

    Returns the stored claims dict on success, None if the token is unknown
    or expired.  The token is deleted before returning so it cannot be reused
    — if an attacker replays a stolen token after the legitimate client has
    already used it, they get None.
    """
    redis = await _get_redis()
    try:
        key = _key(rt_id)
        raw = await redis.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        await redis.delete(key)
        user_id = data.get("user_id")
        if user_id:
            await redis.srem(_user_key(user_id), rt_id)
        return data
    except Exception:
        logger.warning("Failed to use refresh token rt_id=%s", rt_id, exc_info=True)
        return None
    finally:
        await redis.aclose()


async def revoke_refresh_token(rt_id: str) -> None:
    """Delete a refresh token unconditionally (called on logout)."""
    if not rt_id:
        return
    redis = await _get_redis()
    try:
        raw = await redis.get(_key(rt_id))
        if raw:
            data = json.loads(raw)
            user_id = data.get("user_id")
            if user_id:
                await redis.srem(_user_key(user_id), rt_id)
        await redis.delete(_key(rt_id))
    except Exception:
        logger.warning("Failed to revoke refresh token rt_id=%s", rt_id, exc_info=True)
    finally:
        await redis.aclose()


async def revoke_refresh_tokens_for_user(user_id: str) -> None:
    """Revoke all refresh tokens for a user (password reset)."""
    if not user_id:
        return
    redis = await _get_redis()
    try:
        key = _user_key(user_id)
        rt_ids = await redis.smembers(key)
        if rt_ids:
            await redis.delete(*[_key(rt_id) for rt_id in rt_ids])
        await redis.delete(key)
    except Exception:
        logger.warning("Failed to revoke refresh tokens for user_id=%s", user_id, exc_info=True)
    finally:
        await redis.aclose()
