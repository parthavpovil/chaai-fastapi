# Scalable Worker Timeout Fix — arq Cron Jobs + Event Loop Unblock

## Problem
The earlier fix (Redis leader-election + `preload_app = False`) reduced duplicate background work across workers but did **not** stop `WORKER TIMEOUT` / SIGKILL on the web containers. New logs showed workers going silent ~60s after a WebSocket connection opened, then being killed.

Three load-bearing causes identified:

1. **Tight Redis pub/sub polling loop** in `app/services/redis_pubsub.py` — the listener called `get_message(timeout=0.01)` then `asyncio.sleep(0.005)` in a hot loop (≈67 Hz). Whenever Redis stalled, the loop monopolized the event loop and starved WebSocket handlers running in the same worker.
2. **Singleton background tasks ran inside web workers**. Even with leader election, monitoring / agent-status / reconciliation / metrics still executed on the leader web worker's event loop and consumed its memory budget (~333 MB per worker on a 1 GB container).
3. **`_lock` held across `websocket.close()`** in the customer-side `disconnect()` — a slow client could stall every other WS op on the worker.

## Changes

### New file
- `app/tasks/scheduled_jobs.py` — four thin arq job wrappers (`run_agent_status_check`, `run_reconciliation_sweep`, `run_metrics_collection`, `run_health_check`) that reuse existing service logic (`_mark_stale_agents_offline`, `_reconcile`, `MetricsService`, `AlertingService`).

### `app/tasks/message_tasks.py`
- Imported `cron` from arq and the four scheduled job functions.
- Added a `cron_jobs` list to `PaidMessageWorkerSettings` with `unique=True` (Redis-locked exactly-once execution):
  - `run_agent_status_check` — every 1 minute
  - `run_reconciliation_sweep` — every 1 minute
  - `run_metrics_collection` — every 1 minute
  - `run_health_check` — every 5 minutes
- `FreeMessageWorkerSettings` intentionally has no cron_jobs (single source of truth).

### `main.py`
- Deleted the `_leader_loop()` function and all leader-election state (`_LEADER_KEY`, `_LEADER_TTL`, `_LEADER_POLL`).
- Removed now-unused imports: `os`, `socket`, `redis.asyncio as aioredis`.
- Lifespan now only starts per-worker tasks: stale customer-WS cleanup and the Redis pub/sub listener.

### `app/services/redis_pubsub.py`
- Replaced the 67 Hz polling loop in `start_listener()` with `async for msg in pubsub.listen()`. The coroutine now parks on Redis's native blocking read and only resumes when a message arrives. `asyncio.CancelledError` is re-raised cleanly; other exceptions trigger a 1-second reconnect.

### `app/routers/websocket.py`
- Added `_WS_DB_QUERY_TIMEOUT = 5.0`.
- Wrapped DB-dependent calls in `handle_stats_request`, `handle_conversations_request`, `handle_agents_request` with `asyncio.wait_for(..., timeout=_WS_DB_QUERY_TIMEOUT)`.
- Each handler now catches `asyncio.TimeoutError` and sends the client `{"type": "error", "code": "query_timeout", "message": "..."}` instead of hanging the worker.

### `app/services/websocket_manager.py`
- **Agent `disconnect()`** — added explicit `return True` so all success paths return `True` (previously returned implicit `None` when the workspace pool still had connections).
- **Customer `disconnect()`** — moved `await connection.websocket.close()` outside the `_lock` block so a slow client can no longer stall other WS ops on the worker.
- Documented the `_lock` invariant on both lock declarations: never hold `_lock` across a network/await call.

## What This Achieves

| Before | After |
|---|---|
| Web workers ran 5 recurring DB jobs in their event loop | Web workers do only HTTP / WebSocket I/O |
| Pub/sub listener polled 67×/sec, freezing on Redis stalls | Listener parks on Redis blocking read; zero CPU at idle |
| WS handler DB queries could hang the worker indefinitely | Queries abort at 5s and notify the client |
| Customer `_lock` held across `websocket.close()` could stall the worker | Lock released before any network I/O |
| Hand-rolled Redis leader election | Replaced by arq's built-in `unique=True` cron lock |

## Deploy Order

1. Deploy first — paid worker picks up cron jobs immediately. Verify with `docker logs chatsaas-message-worker-paid | grep -E "run_(agent_status|reconciliation|metrics|health)"`.
2. Verify web workers no longer log `Starting monitoring tasks` / `Reconciliation sweeper started` on startup.
3. Watch `docker logs chatsaas-backend | grep "WORKER TIMEOUT"` — should remain empty.
4. Watch `docker stats chatsaas-backend` — per-worker RSS should stabilize lower than before.

## Resource Limits (docker-compose.prod.yml)

VPS verified at 7.8 GB total RAM, 6.0 GB available — OOM was **not** the cause of the original WORKER TIMEOUTs (the event-loop fixes above were). Two targeted bumps for efficiency:

| Service | Before | After | Why |
|---|---|---|---|
| Redis | 256 MB | 512 MB | Hosts arq queue, pub/sub, cache. 256 MB was tight under load. Also added `--maxmemory 432mb --maxmemory-policy noeviction` so Redis fails writes loudly instead of being silently OOM-killed by the kernel. |
| Backend | 1 GB | 1.28 GB | 3 Gunicorn workers now get ~416 MB each (was ~333 MB). Comfortable headroom for WebSocket buffers and per-request objects. |

Total declared limits across all containers: 5.4 GB → 5.95 GB. Sits inside the 6.0 GB available; actual usage will be much lower since Docker memory limits are caps, not preallocations.

## Not Covered

- Gunicorn worker count tuning (currently `min(cpu_count() * 2 + 1, 4)`) — revisit only if memory pressure persists after this fix.
