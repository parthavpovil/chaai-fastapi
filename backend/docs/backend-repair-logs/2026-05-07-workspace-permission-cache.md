# §9.4 — Workspace Permission Cache (Redis TTL-60s)

## Problem

Every authenticated request that passes through `require_permission(key)` issued
4–5 sequential Postgres queries:

| # | Query | Location |
|---|---|---|
| 1 | SELECT user WHERE id = :user_id | `get_current_user` |
| 2 | SELECT workspace WHERE id = :ws_id | workspace resolution in `require_permission` |
| 3 | SELECT tier_permission_templates WHERE tier_id = :tier | `_load_tier_flags` |
| 4 | SELECT workspace_permission_overrides WHERE workspace_id = :ws_id | `_load_overrides` |

Queries 3 and 4 compute the effective permission map — data that changes at most
once per hour (on tier upgrades or explicit permission overrides).  Re-fetching it
on every request is wasteful without a caching layer.

**Severity:** MEDIUM — every request with a permission gate pays the cost.

## Fix

### New module: `app/services/workspace_cache.py`

Provides three async helpers that follow the existing codebase pattern
(`token_blocklist.py` / `razorpay_service.py`):

```python
get_cached_permissions(workspace_id, role)    → dict | None
set_cached_permissions(workspace_id, role, perms)
invalidate_workspace_cache(workspace_id)
```

Cache key: `perm:{workspace_id}:{role}`  
TTL: **60 seconds** — acceptable stale window; permissions almost never change
within a 1-minute window and the TTL acts as a safety net even without
explicit invalidation.

All three functions are **fail-open** — any Redis error is logged at DEBUG level
and execution continues as if there were a cache miss.  A Redis outage therefore
degrades to the pre-cache baseline (extra DB queries) rather than breaking auth.

### `permission_service.get_effective_permissions`

Check-before-compute, write-after-compute:

```python
cached = await get_cached_permissions(str(workspace.id), role)
if cached is not None:
    return cached
# ... compute tier_flags + overrides + effective map ...
await set_cached_permissions(str(workspace.id), role, effective)
return effective
```

### Explicit invalidation

`invalidate_workspace_cache(workspace_id)` is called (after `db.commit()`) in:

| File | When |
|---|---|
| `permission_service.upsert_overrides` | Permission override saved |
| `razorpay_service.handle_subscription_activated` | Tier upgraded via Razorpay |
| `razorpay_service.handle_subscription_cancelled` | Tier downgraded to free |
| `admin_service.AdminService.update_workspace_tier` | Tier changed by admin |

The invalidation scans `perm:{workspace_id}:*` to delete all role variants
in one SCAN+DEL without hard-coding the role list.

## Query impact per request

| Path | Before | After (cache hit) |
|---|---|---|
| `require_permission(key)` cold | 4 queries | 4 queries (Miss → warm cache) |
| `require_permission(key)` warm | 4 queries | 2 queries (User + Workspace) |
| Tier change / override upsert | — | +1 cache invalidation (best-effort) |

## What is NOT cached

- **User row** (`SELECT user WHERE id = ...`) — user.is_active can change (deactivation);
  a 60-second stale window could allow a deactivated user one extra request per minute.
  Left for a later audit.
- **Workspace row** (`SELECT workspace WHERE id = ...`) — the ORM object is used
  downstream for `SELECT FOR UPDATE` in tier checks and for relationship access.
  Caching a serialised dict and reconstructing it is more invasive; left for later.

## Files Changed

- `app/services/workspace_cache.py` (new)
- `app/services/permission_service.py` — cache check/set in `get_effective_permissions`;
  invalidation in `upsert_overrides`
- `app/services/razorpay_service.py` — invalidation in `handle_subscription_activated`
  and `handle_subscription_cancelled`
- `app/services/admin_service.py` — invalidation in `update_workspace_tier`

## Testing Checklist

- [ ] First request after server start: cache miss, 4 DB queries (verify via query log)
- [ ] Second request same workspace+role within 60 s: cache hit, 2 DB queries
- [ ] Change tier via admin API → next request sees new permissions immediately
- [ ] Upsert permission override → next request reflects the override immediately
- [ ] Kill Redis → requests fall back to 4 DB queries without error
- [ ] Razorpay subscription.activated webhook → permission cache for workspace cleared
