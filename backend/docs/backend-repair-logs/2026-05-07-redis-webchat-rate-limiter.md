# Replace Postgres ARRAY Rate Limiter with Redis

## Original Problem

`app/services/rate_limiter.py` stored request timestamps in a Postgres ARRAY column
(`rate_limits.request_timestamps`). Every incoming WebChat message caused:
1. SELECT the rate_limit row for this session
2. UPDATE the row to append a new timestamp to the ARRAY
3. COMMIT

Under concurrent load (many chat sessions simultaneously), this produced hot-row
contention on the `rate_limits` table. The array grew unboundedly until a cleanup
ran. Postgres is not a rate limiter.

**Severity:** HIGH — write storm under load, wrong tool for the job.

## Root Cause

Postgres ARRAY used as a sliding-window store. Correct tool is Redis INCR with EXPIRE.

## Fix Strategy

Rewrite `check_webchat_rate_limit` using Redis fixed-window counter:
- Key: `webchat_rl:{workspace_id}:{session_token}`
- Limit: 10 messages per 60 seconds
- Algorithm: atomic INCR + conditional EXPIRE via Lua script
- Fail-open on Redis errors (same pattern as auth_rate_limit.py)

Keep the public API (`RateLimitExceededError`, `check_webchat_rate_limit`) unchanged
so callers in webchat.py need minimal updates.

The `rate_limits` DB table is now unused — it will be dropped in a future
cleanup migration once we confirm no other code references it.

## Exact Backend Changes

### Rewritten: `app/services/rate_limiter.py`
- Removed: `RateLimiter`, `WebChatRateLimiter`, `APIRateLimiter` classes
  (never imported outside this file)
- Removed: all SQLAlchemy/DB dependencies
- Kept: `RateLimitExceededError` (callers catch this)
- Rewrote: `check_webchat_rate_limit(session_token, workspace_id, db=None)`
  as a Redis INCR+EXPIRE implementation
  (`db` param kept with default=None for backward compat, ignored)

### Modified: `app/routers/webchat.py`
- Removed `db=db` from both `check_webchat_rate_limit` call sites
  (no longer needed — the function doesn't use the DB session)

### Unchanged: `app/models/rate_limit.py`, `rate_limits` DB table
- Table is now idle — left in place to avoid a destructive migration during
  this sprint. Drop in a future cleanup pass.

## Frontend Impact

✅ No frontend changes needed.
Same 429 response format and RateLimitExceededError message.

## Testing Added

- Manual: send 11 webchat messages within 60 seconds from the same session —
  11th should return 429 with rate limit message.
- Manual: different session tokens should have independent rate limit buckets.
- Manual: Redis down scenario — requests should complete (fail-open).
- Regression: normal 1–10 message flow should be unaffected.
- Performance: check that hot-path DB queries for rate_limits table have
  disappeared from slow-query logs.

## Deployment Notes

- Rolling Gunicorn restart picks up the change.
- Redis keys expire automatically after 60s — no cleanup needed.
- Old `rate_limits` table rows will go stale but won't grow further.
- Rollback: revert rate_limiter.py to previous version (git revert).
  The `rate_limits` table will resume being used.

## Final Outcome

WebChat rate limiting is now O(1), lock-free, and handled entirely in memory.
The `rate_limits` table will no longer receive writes.

## Next Recommended Fix

**H5 — No DLQ, no Sentry, no structured logs, no request-id**
Terminal arq job failures are silently dropped. No exception aggregation.
No request correlation IDs. Hardest observability gap to close.
OR
**H6 — Workspace hard-delete cascades through 17 relations (no soft delete)**
Simpler schema change — add deleted_at columns and replace DELETE with UPDATE.
