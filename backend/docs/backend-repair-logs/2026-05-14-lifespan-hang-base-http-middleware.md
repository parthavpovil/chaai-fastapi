# Lifespan startup hang — BaseHTTPMiddleware → pure ASGI

## Problem

After a deploy, backend containers never reached the `healthy` state. Each
gunicorn `UvicornWorker` logged:

```
[INFO] uvicorn.error: Started server process [33]
[INFO] uvicorn.error: Waiting for application startup.
```

…and then went silent. **`Application startup complete.` never fired.**
`curl http://localhost:8000/health` from inside the container hung indefinitely
(0 bytes received after 15 s, even ~4 min after worker spawn). The deploy
script's wait loop exhausted (~6 min) and rolled back.

Diagnostic logs added to the FastAPI `lifespan` confirmed the lifespan body
itself completed through `yield` successfully:

```
LIFESPAN: enter
LIFESPAN: sentry inited, calling init_db
LIFESPAN: init_db done
LIFESPAN: cleanup task scheduled
LIFESPAN: redis pubsub task scheduled, about to yield
```

…but nothing after `yield`. Per Starlette 0.37.2, the next step is
`await send({"type": "lifespan.startup.complete"})` — which never reached
uvicorn's startup loop.

**Severity:** Critical. Every deploy was rolling back; no path to production.

## Root Cause

Two middleware in the ASGI stack were wrapping the application — including the
lifespan handler — in `BaseHTTPMiddleware`:

1. `SplitCORSMiddleware(BaseHTTPMiddleware)` added via `app.add_middleware(...)`.
2. `maintenance_mode_middleware` registered with `@app.middleware("http")`. The
   decorator silently wraps the dispatch function in `BaseHTTPMiddleware` —
   easy to miss because the call site looks like a function registration.

On Starlette 0.37.x + uvicorn 0.29.0 running under gunicorn's `UvicornWorker`,
this combination breaks the lifespan handshake. Although `BaseHTTPMiddleware`
does forward non-HTTP scopes, its construction sets up anyio task-group /
exit-stack state that interferes with uvicorn observing
`lifespan.startup.complete`. The worker stays parked on
`Waiting for application startup.` forever.

The investigation log (`DEPLOY_INVESTIGATION.md` §3 H3 and §7) already
identified `BaseHTTPMiddleware` replacement as the recommended permanent fix.
This repair applies it.

Two ancillary issues were resolved at the same time:

- `@app.on_event("startup") _debug_post_yield_marker` was registered after
  `FastAPI(lifespan=...)` was constructed. With a custom lifespan, Starlette
  silently ignores `on_event` handlers, so the diagnostic never logged —
  which misled the investigation (§2.5). Removed.
- The lifespan body created two background tasks (`cleanup_stale_customer_connections`,
  `redis_pubsub.start_listener`) but never cancelled them on shutdown,
  leaking them when the worker terminated. Now they're held and cancelled
  inside the lifespan's shutdown phase.

## Fix

### `main.py`

- **Restored real lifespan body** (Sentry init, `init_db()`, cleanup task,
  redis pubsub listener). Tasks are now assigned to local names and explicitly
  `.cancel()`-ed after `yield`, then `await close_db()`.
- **Removed the dead `@app.on_event("startup")` debug handler.** Inert with a
  custom lifespan, and its absence in logs had been used as evidence in §2.5
  — a flawed diagnostic that confused the investigation.
- **Converted `SplitCORSMiddleware` from `BaseHTTPMiddleware` to pure ASGI.**
  Implements `async __call__(scope, receive, send)` directly, short-circuits
  on `scope["type"] != "http"`, and writes CORS headers by wrapping `send`
  for `http.response.start`. `OPTIONS` preflight is answered directly without
  delegating to the inner app.
- **Replaced `app.middleware("http")(maintenance_mode_middleware)` with
  `app.add_middleware(MaintenanceModeMiddleware)`.** Eliminates the implicit
  `BaseHTTPMiddleware` wrap from the decorator.
- Dropped now-unused imports (`BaseHTTPMiddleware`, `Response`) and added
  `starlette.types` (`ASGIApp`, `Receive`, `Scope`, `Send`).
- Prometheus instrumentator kept commented out for this deploy; re-enable
  once the fix is verified in production. The earlier commit that disabled
  Prometheus did so as a separate diagnostic step — it was not by itself
  sufficient because both BaseHTTPMiddleware instances remained.

### `app/middleware/maintenance_middleware.py`

- Added `MaintenanceModeMiddleware` — a pure-ASGI class that performs the same
  three jobs as the old function: allow-list bypass for health/auth/admin
  paths, 503 + `Retry-After` for non-admins during maintenance, pass-through
  with `X-Maintenance-Mode` / `X-Admin-Access` response headers for admins.
- The new middleware constructs a `starlette.requests.Request` from `(scope,
  receive)` to reuse `is_allowed_endpoint(path)` and `is_admin_user(request)`
  without changing their signatures. Headers are added by wrapping `send` to
  intercept the `http.response.start` message.
- The 503 maintenance response is delivered by calling the existing
  `JSONResponse` instance as an ASGI app: `await response(scope, receive, send)`.
- Removed the old `maintenance_mode_middleware(request, call_next)` function.
  No other module imported it directly (only `main.py`).

## Why pure ASGI is the right primitive here

Both `SplitCORSMiddleware` and `MaintenanceModeMiddleware` only need to:

1. Inspect the request path / headers (available from `scope` without
   consuming `receive`).
2. Decide whether to short-circuit (preflight, maintenance, allow-list).
3. Optionally wrap `send` to add response headers.

None of those operations needs the higher-level convenience that
`BaseHTTPMiddleware` provides (a fully-buffered `Response` object). Writing
them as ~30-line ASGI classes is no more code than the `BaseHTTPMiddleware`
versions and avoids the lifespan interaction entirely. It's the migration
Starlette's own documentation recommends.

## Verification

- `docker build` succeeded with the changes (image
  `chatsaas-backend:local-test`, 658 MB, exit 0).
- `python -m py_compile` clean on both files.
- Inside the container, `python -c "import main"` completes and inspection of
  `app.user_middleware` shows the expected stack — `RequestIDMiddleware →
  MonitoringMiddleware → MaintenanceModeMiddleware → SplitCORSMiddleware →
  app` — with zero `BaseHTTPMiddleware` instances. `app.router.lifespan_context`
  is bound to the new `lifespan` function.

Post-deploy verification (operator): tail `docker logs` for the backend
container after deploy and confirm `Application startup complete.` appears
within ~30 s of `Waiting for application startup.`. `/health` should respond
within the same window.

## Frontend Impact

None. CORS headers, preflight handling, and the 503 maintenance response are
all preserved exactly.

## Files Changed

- `main.py`
- `app/middleware/maintenance_middleware.py`

## Related

- `DEPLOY_INVESTIGATION.md` (project root) — full investigation log, hypotheses
  H1–H5, and the diagnostic timeline that led here.
- §7 of the investigation already recommended the BaseHTTPMiddleware →
  pure-ASGI migration as a permanent improvement; this repair implements it.

## Follow-ups (not in this repair)

- Re-enable Prometheus instrumentator after deploy confirms the hang is
  resolved. Consider moving its setup inside the lifespan body before `yield`
  rather than at module top level.
- Remove the duplicate `alembic upgrade head` between `deploy.yml:221` and
  `entrypoint.sh:5` (~30–60 s saved per cold start).
- Split `/health` into `/livez` (cheap 200 OK) and `/readyz` (DB + R2 checks)
  so the docker healthcheck is decoupled from dependency probing.
- Fix the leaked `monitoring_middleware = init_monitoring_middleware(app)`
  reference — the global it stores is never added to the middleware stack,
  so `/metrics/middleware` reads metrics from a phantom instance that never
  sees requests.
