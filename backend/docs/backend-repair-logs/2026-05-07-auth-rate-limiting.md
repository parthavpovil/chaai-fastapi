# Auth Endpoint Rate Limiting

## Original Problem

`/api/auth/login`, `/api/auth/agent-login`, and `/api/auth/register` had zero
rate limiting. A botnet could attempt thousands of credential pairs per second
against bcrypt, saturating CPU on Gunicorn workers with no throttle.

Nginx had a global `limit_req` at 10 req/s per IP — too coarse and easily
bypassed from a distributed botnet.

**Severity:** CRITICAL

## Root Cause

No rate limit dependency on the auth endpoints. The existing `RateLimiter`
service was not wired in, and it uses Postgres ARRAY storage (§9.1) which is
the wrong tool for this anyway.

## Fix Strategy

New Redis-backed fixed-window rate limiter in `app/services/auth_rate_limit.py`:
- Key: `auth_rl:{endpoint}:{email}:{ip}` — per email+IP pair
- Limit: 10 attempts per 5 minutes
- Algorithm: atomic Redis INCR+EXPIRE via Lua script (same pattern as the
  workspace concurrency semaphore in `message_tasks.py`)
- Fail-open: Redis errors are logged and the request passes through (avoids
  locking out all users during a Redis outage)
- Returns HTTP 429 with `Retry-After` header when limit exceeded

Deliberately NOT using the existing `RateLimiter` (Postgres ARRAY) — that is
a known performance issue (§9.1) that will be fixed separately.

## Exact Backend Changes

### New file: `app/services/auth_rate_limit.py`
- `check_auth_rate_limit(request, email, endpoint)` — raises 429 if exceeded

### Modified: `app/routers/auth.py`
- Added `Request` to FastAPI imports
- Added `from app.services.auth_rate_limit import check_auth_rate_limit`
- Added `http_request: Request` parameter to `register_user`, `login_user`, `login_agent`
- Added `await check_auth_rate_limit(...)` as first call in each handler

No DB migrations. No schema changes.

## Frontend Impact

⚠ Frontend changes required (minor — new HTTP status to handle)

### New HTTP status
- `HTTP 429 Too Many Requests` is now possible from `/login`, `/agent-login`, `/register`
- Response body: `{"detail": "Too many attempts. Try again in N seconds."}`
- Response header: `Retry-After: N`

### Frontend TODO
- Handle 429 on login/register forms
- Show user-friendly message: "Too many login attempts. Please wait N seconds."
- Disable the submit button and show countdown using `Retry-After` header value

### Frontend Documentation File
`/docs/frontend-changes/2026-05-07-auth-rate-limit-429.md`

### Backward Compatibility
Previously 429 was never returned from auth endpoints. Existing frontend
code that only handles 401/400 will silently ignore or mishandle 429.
Most frameworks treat unknown 4xx as errors and show a generic message —
acceptable but not ideal. Frontend should be updated to show a clear message.

## Testing Added

- Manual: POST `/api/auth/login` 11 times with same email from same IP within
  5 minutes — 11th request should return 429 with `Retry-After` header.
- Manual: Different email from same IP — should NOT be blocked (separate key).
- Manual: Redis down scenario — requests should still complete (fail-open).
- Regression: Normal login flow should be unaffected on first 10 attempts.

## Deployment Notes

- Rolling Gunicorn restart picks up the new module.
- No DB migration needed.
- Redis key TTL is 5 minutes — keys expire automatically, no cleanup needed.
- Rollback: remove the `await check_auth_rate_limit(...)` call from the three
  endpoints and delete `app/services/auth_rate_limit.py`.

## Final Outcome

Auth endpoints are now protected against credential stuffing. An attacker
hammering one email+IP gets blocked after 10 attempts for 5 minutes.

**Remaining gaps (future work):**
- No account lockout after N failures (full lockout is a separate policy decision)
- No CAPTCHA on repeated failures
- JWT is still HS256 with 7-day expiry (§5.2 — separate fix)
- No per-IP limit across all emails (only per email+IP combined)

## Next Recommended Fix

**C4 — Missing composite indexes on conversation list queries**
`(workspace_id, updated_at)` and `(workspace_id, status)` on `conversations` table.
Pure DB migration, no code changes, no frontend impact.
