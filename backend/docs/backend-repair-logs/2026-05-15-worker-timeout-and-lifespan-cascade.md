# Worker timeout cascade + lifespan hang — full investigation and repair

## Problem

Two separate failure modes had been alternating for ~24h, each made worse
by attempted fixes to the other:

1. **Deploy healthcheck hang.** Gunicorn workers reached `Waiting for
   application startup.` and never logged `Application startup complete.`
   The container stayed `unhealthy`, the deploy script's wait loop
   exhausted (~6 min) and rolled back.

2. **WORKER TIMEOUT / SIGKILL after widget activity.** When the deploy did
   succeed, workers ran for a minute or two and then started dying every
   ~70 s with `[CRITICAL] WORKER TIMEOUT (pid:XX)` followed by
   `Worker (pid:XX) was sent SIGKILL! Perhaps out of memory?`. New workers
   spawned and died the same way. /api/webchat/send returned 504 from
   nginx because the handler never completed in 60 s.

**Severity:** Critical. No reliable deploy path — either it never came up,
or it came up and then degraded into a cascade of dying workers within
minutes of a real chat session.

The investigation was complicated by chasing the wrong cause twice
(BaseHTTPMiddleware, then gunicorn `preload_app`). The full investigation
log lives in `DEPLOY_INVESTIGATION.md` at the repo root.

## Root causes (three distinct bugs)

### A. `redis_pubsub.start_listener` busy-looped when no subscriptions

`pubsub.listen()` in redis-py is implemented as `while self.subscribed: ...`
— with zero subscribed channels it returns the async iterator empty and
exits immediately. The wrapping reconnect loop then re-entered with no
`await` between iterations:

```python
while True:
    pubsub = self._get_pubsub()
    async for msg in pubsub.listen():   # exits immediately if no subs
        ...
    # no sleep, no yield — CPU-tight loop
```

On a fresh worker (no WS clients yet → no subscriptions) the lifespan
task spawned by `asyncio.create_task(redis_pubsub.start_listener(...))`
spun the event loop at 100% CPU. Starlette's post-yield
`await send({"type": "lifespan.startup.complete"})` could never get
scheduled, so uvicorn never observed the lifespan complete and
gunicorn never marked the worker ready.

**This is what made the deploy hang.** It looked like middleware or
`preload_app` because the symptom was identical — workers stuck on
`Waiting for application startup.` — but the cause was an event-loop
busy spin.

### B. `Depends(get_db)` on WebSocket endpoints leaked DB connections for the entire WS lifetime

Both `/ws/{workspace_id}` (agent) and `/ws/webchat/{workspace_id}`
(customer) had `db: AsyncSession = Depends(get_db)` on the route
signature. For HTTP this is request-scoped (correct). For WebSocket
FastAPI keeps the dependency alive for the entire connection — so the
auth-time `SELECT channels...` opened a transaction and the session
sat in "idle in transaction" state until the WS closed.

`pg_stat_activity` showed this directly: connections with
`state = 'idle in transaction'`, `wait_event = ClientRead`, and
`age(now(), query_start)` of 14+ seconds.

DB_POOL_SIZE=10 + max_overflow=5 per gunicorn worker × 4 workers gives
up to 60 connections, but every concurrent WS client pinned one
permanently. With even modest WS traffic the pool exhausted; new HTTP
handlers blocked waiting on `pool_timeout=30 s`; gunicorn's heartbeat
(needed every 60 s with `timeout=120 s`) couldn't run while the loop
sat in `acquire()`; master sent SIGKILL.

**This is what made workers die after widget activity.**

### C. `CustomerWebSocketManager._lock` held across `await old.websocket.close()`

Commit d7250a9 had introduced a documented invariant on the agent-side
manager: never hold `_lock` across a network/await call. Same pattern
on the customer manager was missed — when a widget reconnected with the
same session_token, `connect()` ran `await old.websocket.close()`
while holding `_lock`. If the old client was unresponsive (frozen tab,
flaky network) that close stalled, every other operation on the
manager queued behind it, and reconnect cascades stacked up.

Less catastrophic than A and B, but it widened any small stall into a
worker-wide stall and contributed to the visible timeouts.

## Why the investigation went sideways

I (Claude) made two wrong calls before getting to the real cause:

1. **First wrong guess: `BaseHTTPMiddleware`.** Two BaseHTTPMiddleware
   instances were in the stack (`SplitCORSMiddleware`,
   `@app.middleware("http")(maintenance_mode_middleware)`). I converted
   both to pure-ASGI middlewares thinking the lifespan handshake was
   stuck in middleware initialization. Deployed — still hung. Reverted
   that PR. The conversion itself wasn't wrong, just irrelevant.

2. **Second wrong guess: `preload_app=False`.** The user (correctly)
   pointed at commit 3519962 as where the trouble started. That commit
   changed `preload_app=True → False` AND added a leader-election loop
   in lifespan. After we rolled back to pre-3519962, the deploy came
   up — but only because reverting also undid d7250a9's pubsub change
   (bug A). The healthy state was a lucky byproduct, not a confirmation
   that `preload_app` was the cause.

The real signal was hiding in the logs the whole time:

```
[INFO] uvicorn.error: Waiting for application startup.
[INFO] app.services.redis_pubsub: Redis pub/sub listener started
<silence>
```

"Redis pub/sub listener started" is logged at the top of
`start_listener`. The fact that it appeared meant the lifespan body
ran and yielded — the hang was *after* yield, in code spawned by the
lifespan, not in middleware or lifespan structure. I should have read
that more carefully and gone straight to `start_listener`.

## Fixes

### `backend/app/services/redis_pubsub.py` — fix bug A
Park on `asyncio.sleep(0.5)` until at least one subscription exists,
then call `pubsub.listen()` which is safe to block on. Documented why
the guard is required (because `listen()` is `while self.subscribed: ...`
and a tight loop with no awaits will starve the event loop).

```python
while True:
    try:
        while not self._subscriptions:
            await asyncio.sleep(0.5)
        pubsub = self._get_pubsub()
        async for msg in pubsub.listen():
            ...
    except asyncio.CancelledError:
        raise
    except Exception:
        ...
        await asyncio.sleep(1)
```

Verified with a stub-DB lifespan smoke test inside the container:
"PAST YIELD" reached in <2 s, event loop ticks every 500 ms (not
CPU-pinned), clean shutdown.

### `backend/app/routers/websocket.py` + `websocket_webchat.py` — fix bug B
- Removed `db: AsyncSession = Depends(get_db)` from both WebSocket
  endpoint signatures.
- Opened a short-lived `AsyncSessionLocal()` for the auth lookup, and
  a fresh session per inbound message (released as soon as the
  handler returns).
- HTTP endpoints in the same files still use `Depends(get_db)` —
  that's correct for request-scoped sessions.

### `backend/app/services/websocket_manager.py` — fix bug C
`CustomerWebSocketManager.connect`: capture the to-be-replaced
connection inside `_lock`, do the `await old.websocket.close()`
outside it. Mirrors what d7250a9 did for the agent manager.

### Architecture changes that survived the rollback round-trip
These came in with d7250a9 / 3519962 originally, were rolled back, and
were re-applied (without the bug-A pubsub change as it was) as part of
this repair:

- `backend/app/tasks/scheduled_jobs.py` (new): cron wrappers for
  agent-status / reconciliation / metrics / health.
- `backend/app/tasks/message_tasks.py`: `PaidMessageWorkerSettings`
  registers all 4 as arq cron jobs with `unique=True` (Redis-locked
  to run exactly once across the worker pool, no in-app leader
  election needed).
- `backend/main.py`: lifespan no longer starts singleton bg tasks
  inside web workers — only per-worker tasks (stale-WS cleanup,
  Redis pubsub listener). This eliminates 4× duplicate DB-heavy
  tasks across the 4 gunicorn workers.

### Intentionally NOT changed
- `backend/gunicorn.conf.py`: kept `preload_app=True` (which the
  rollback restored). The pre-3519962 hypothesis blaming
  `preload_app=False` is unproven; the real cause of the lifespan
  hang was bug A, which happens regardless of `preload_app`. We
  left preload_app=True because the rollback established it as a
  known-good baseline for the deploy handshake.

## Verification

Live VPS (`docker logs chatsaas-backend`) after the fix chain:

```
[INFO] Application startup complete.   (pid 51)
[INFO] Application startup complete.   (pid 52)
[INFO] Application startup complete.   (pid 53)
[INFO] Application startup complete.   (pid 54)
... no WORKER TIMEOUT ...
```

`pg_stat_activity` no longer shows "idle in transaction" connections
sitting >1 s after a WS open.

`chatsaas-message-worker-paid` arq logs show all 4 cron functions
firing on schedule (every 1m for agent-status / reconciliation /
metrics; every 5m for health), completing in <1 s each.

## Files Changed

- `backend/app/services/redis_pubsub.py`
- `backend/app/routers/websocket.py`
- `backend/app/routers/websocket_webchat.py`
- `backend/app/services/websocket_manager.py`
- `backend/app/tasks/scheduled_jobs.py` (new)
- `backend/app/tasks/message_tasks.py`
- `backend/main.py`

(No changes to `backend/gunicorn.conf.py`.)

## Related commits

- `107e219` — fix(redis_pubsub): guard listen() loop when no subscriptions exist  (fix A)
- `ad7b6b4` — fix(ws): scope DB session per message + close replaced WS outside lock  (fixes B and C)
- `bdd84bc` — fix(workers): move singleton bg tasks to arq cron + restore d7250a9 architecture
- `97d0866` — Revert "feat(gunicorn)..." and 7 subsequent commits to pre-3519962 state (rollback baseline)

## Frontend Impact

None. Customer-side widget and dashboard behavior unchanged. After the
fix, /api/webchat/send returns 200 instead of the 504s seen earlier.

## Follow-ups (separate work)

- **/api/webchat/send is still slow on cold cache** — currently 10–47 s
  on the first request, because `get_webchat_channel_by_widget_id`
  fetches every webchat channel and Fernet-decrypts every field of
  every config to find the one whose decrypted `widget_id` matches.
  Tracking separately; fix is in flight.
- Long-term: promote `widget_id` to its own indexed column on
  `channels` so the lookup is `WHERE widget_id = $1` and the
  decrypt-everything loop goes away entirely.
- Re-enable Prometheus instrumentator after stability is confirmed for
  a few days.
- Clean up the orphan `chatsaas-message-worker` container (7-day-old
  image, status `unhealthy`, not picking up new-queue jobs but still
  burning a small amount of CPU and one Redis connection).
- The two arq worker containers show `unhealthy` because they inherit
  the Dockerfile's `curl :8000/health` HEALTHCHECK but don't serve
  HTTP. Cosmetic only — the deploy gate ignores them — but adding
  `healthcheck: disable: true` for both worker services in
  `docker-compose.prod.yml` would clean up `docker ps` output.
