"""
Workspace permission cache.

Caches the computed effective permission map per (workspace_id, role) in Redis
with a 60-second TTL.  Permissions change at most once per hour (tier upgrade /
permission override), so a 60-second stale window is acceptable and saves 2
Postgres round-trips on every permission-gated request.

Invalidation is explicit:
  - call invalidate_workspace_cache(workspace_id) after:
      * workspace.tier changes  (tier upgrade / downgrade)
      * WorkspacePermissionOverride is upserted
      * workspace is soft-deleted
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_TTL = 60  # seconds — stale window is acceptable; tier/override changes are rare


def _perm_key(workspace_id: str, role: str) -> str:
    return f"perm:{workspace_id}:{role}"


def _redis():
    """Process-wide pooled Redis client. Never aclose() per call."""
    from app.services.redis_client import get_redis
    return get_redis()


async def get_cached_permissions(workspace_id: str, role: str) -> Optional[dict]:
    """Return cached effective permission map, or None on miss / Redis error."""
    try:
        r = _redis()
        raw = await r.get(_perm_key(str(workspace_id), role))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("Permission cache read error (workspace=%s role=%s): %s", workspace_id, role, exc)
        return None


async def set_cached_permissions(workspace_id: str, role: str, perms: dict) -> None:
    """Cache effective permission map with TTL. Fails silently on Redis error."""
    try:
        r = _redis()
        await r.set(_perm_key(str(workspace_id), role), json.dumps(perms), ex=_TTL)
    except Exception as exc:
        logger.debug("Permission cache write error (workspace=%s role=%s): %s", workspace_id, role, exc)


async def invalidate_workspace_cache(workspace_id: str) -> None:
    """
    Delete all permission cache entries for a workspace.

    Called after: workspace.tier change, permission override upsert, soft-delete.
    Uses SCAN to match both role variants without hard-coding them.
    Fails silently — a stale cache entry just causes one extra DB query.
    """
    try:
        r = _redis()
        pattern = f"perm:{workspace_id}:*"
        keys = [k async for k in r.scan_iter(pattern)]
        if keys:
            await r.delete(*keys)
    except Exception as exc:
        logger.debug("Permission cache invalidation error (workspace=%s): %s", workspace_id, exc)
