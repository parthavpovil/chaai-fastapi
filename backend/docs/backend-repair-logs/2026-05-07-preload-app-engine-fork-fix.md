# preload_app=True + Async SQLAlchemy Engine Fork Safety

## Original Problem

`gunicorn.conf.py` had `preload_app = True`, which imports the full FastAPI app
in the master Gunicorn process before forking workers. Importing `app.database`
executes `create_async_engine(...)` at module level. The `AsyncAdaptedQueuePool`
carries asyncio-linked internal state. When Gunicorn forks, every worker inherits
a shared copy of this pool — including file descriptors and event-loop references
that belong to the master process. `asyncpg` and SQLAlchemy's async pool are not
fork-safe.

**Severity:** CRITICAL — latent corruption bug in production.

## Root Cause

`app/database.py` creates the engine at import time (module-level global). With
`preload_app=True` Gunicorn imports the module in master, then forks. Each worker
inherits the same engine object with the same pool internals. Workers start their
own `asyncio` event loops, but the pool still references the master loop's state.

## Current System Flow (before fix)

```
Master process
  → import app → database.py:14 → AsyncAdaptedQueuePool created
  → fork worker 1..4
      each worker inherits master's engine + pool
      each worker starts fresh uvicorn asyncio loop
      first DB call in worker uses inherited (stale) pool state  ← bug
```

## Risk Analysis

| Risk | Assessment |
|---|---|
| Connection corruption after fix | None — dispose forces lazy reconnect per worker |
| Startup latency increase | None — connections are lazy |
| Worker restart behavior | Safe — post_fork fires on every restart |
| Frontend / API impact | None |

## Fix Strategy

Keep `preload_app = True` (preserves shared memory for large import trees). Add a
single `engine.sync_engine.pool.dispose()` call inside the existing `post_fork`
hook. This marks all inherited connections as discarded; each worker creates fresh
connections lazily from its own event loop on first request.

This is the canonical SQLAlchemy-recommended pattern for Gunicorn + async engines.

## Exact Backend Changes

**File changed:** `backend/gunicorn.conf.py`

```python
# post_fork hook — before
def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

# post_fork hook — after
def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)
    from app.database import engine
    engine.sync_engine.pool.dispose()
```

No DB migrations. No schema changes. No API changes.

## Frontend Impact

✅ No frontend changes needed.

## Testing Added

- Manual: restart Gunicorn with 4 workers, issue 20 concurrent requests immediately
  after startup — verify no `InvalidRequestError` or connection-reset errors in logs.
- Regression: existing integration tests should pass unchanged.

## Deployment Notes

- Rolling restart of Gunicorn workers is sufficient. No DB migration needed.
- Rollback: revert the 3-line addition to `post_fork`.
- Monitor: watch Gunicorn error logs for `InvalidRequestError` and
  `asyncpg.exceptions.ConnectionDoesNotExistError` — these should disappear.

## Final Outcome

Each Gunicorn worker now creates its own DB connections after fork. The inherited
pool state is discarded before any request is served.

**Remaining risk:** `pool_size` is still unset (defaults to `pool_size=5,
max_overflow=10` per worker). With 4 workers + message-worker container, worst-case
connection count is ~75. On default Postgres `max_connections=100` this is tight.
Addressed in a future fix (§3.8).

## Next Recommended Fix

**H1: Nginx 60s timeout < Gunicorn 120s** (`nginx.conf:38-40`)
Two-line config change. RAG/LLM calls between 60–120s currently return 504 while
the worker keeps processing, causing silent retry storms.
