# Nginx Timeout Mismatch + Global proxy_buffering Off

## Original Problem

`nginx.conf` had all proxy timeouts set to 60s. Gunicorn's `timeout = 120` with
RAG/LLM calls explicitly documented to take 60–90s. Any RAG response in the
60–120s window was killed by Nginx with a 504 while Gunicorn kept processing.

Compounding issue: `proxy_buffering off` was set globally on all routes, disabling
Nginx response buffering on every request and exposing Gunicorn workers to slow-loris
(attacker dribbles response reads, tying up a worker indefinitely).

**Severity:** HIGH (timeout) / MEDIUM (buffering)

## Root Cause

- `proxy_read_timeout 60s` < `gunicorn timeout 120s` — Nginx kills the upstream
  connection before Gunicorn can finish a long RAG call.
- `proxy_buffering off` applied globally instead of only on SSE/streaming routes.

## Current System Flow (before fix)

```
Client → Nginx (proxy_read_timeout=60s) → Gunicorn (timeout=120s) → RAG (60–90s)

t=60s:  Nginx fires 504, client gets error
t=70s:  Client retries → 2nd in-flight job
t=75s:  Gunicorn finishes job 1 → connection dead → answer discarded
Result: 2 LLM calls billed, 0 answers delivered, silent retry storm
```

## Risk Analysis

| Risk | Assessment |
|---|---|
| Raising timeouts breaks fast requests | No — only affects slow requests |
| Re-enabling buffering breaks WebSocket | No — WS is a TCP tunnel after 101; buffering N/A |
| Re-enabling buffering breaks file uploads | No — request buffering (`proxy_request_buffering`) stays off |
| API contract change | None |

## Fix Strategy

1. Set Nginx timeouts slightly above Gunicorn's app timeout (125s > 120s).
   `proxy_connect_timeout` stays low (10s) — connecting to localhost should be instant.
2. Remove `proxy_buffering off` from the global `/` location. Keep
   `proxy_request_buffering off` (needed for streaming large uploads to upstream).
   When SSE streaming endpoints are added later, give them a dedicated
   `location` block with `proxy_buffering off`.

## Exact Backend Changes

**File changed:** `backend/nginx.conf`

### Timeout fix (lines 37–40)
```nginx
# Before
proxy_connect_timeout 60s;
proxy_send_timeout 60s;
proxy_read_timeout 60s;

# After
proxy_connect_timeout 10s;
proxy_send_timeout    125s;
proxy_read_timeout    125s;
```

### Proxy buffering fix (lines 77–78)
```nginx
# Before
proxy_buffering off;
proxy_request_buffering off;

# After
proxy_request_buffering off;
# proxy_buffering intentionally ON (default) — add per-location for SSE
```

No DB migrations. No schema changes. No API changes.

## Frontend Impact

✅ No frontend changes needed.

## Testing Added

- Manual: Issue a request that intentionally takes >60s (mock slow endpoint or RAG
  call) — verify it completes with 200, not 504.
- Regression: Fast endpoints should be unaffected; verify health check, auth, and
  list endpoints still return promptly.
- WebSocket: Open a live chat WebSocket connection and verify messages flow normally
  after proxy_buffering change.

## Deployment Notes

- Reload Nginx: `nginx -s reload` (graceful, no dropped connections).
- No Gunicorn restart needed.
- Rollback: revert `proxy_read_timeout` / `proxy_send_timeout` to 60s and
  restore `proxy_buffering off`.
- Monitor: Watch for 504 errors disappearing from `api.parthavpovil.in.error.log`.

## Final Outcome

RAG/LLM calls up to 120s now complete successfully. Nginx timeout (125s) gives a
5s buffer above Gunicorn's app timeout (120s). Slow-loris vector on response
buffering is closed.

**Remaining risk:** Long-term, responses that take 60–90s give users a blank wait.
Streaming SSE responses (Day 90 item) will fix the UX and make timeout management
trivial since each SSE event resets the read timeout.

## Next Recommended Fix

**C3 — No login rate limiting** (`routers/auth.py`)
Zero rate limiting on `/api/auth/login`, `/api/auth/agent-login`, `/api/auth/register`.
Open to credential stuffing at scale.
