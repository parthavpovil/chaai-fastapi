# Gunicorn Worker Timeout Fix — Distributed Leader Election

## Problem
Workers were being SIGKILL'd every 2–4 minutes with `WORKER TIMEOUT` / `Perhaps out of memory?`.

Two compounding causes:

1. **`preload_app = True` with `UvicornWorker`** — Gunicorn loaded the app in the master process, then forked workers. Forked workers inherited a broken asyncio event loop, asyncpg pool, and Redis connections from the master. Workers would hang trying to use corrupted state, miss the 120s heartbeat, and get killed.

2. **All background tasks ran in every worker** — Each of the 4 Gunicorn workers independently started monitoring, agent-status, reconciliation, stale-WS cleanup, and Redis pub/sub tasks. With 4 workers, all DB-heavy tasks ran 4× simultaneously, exhausting memory and connection pools.

## Changes

### `gunicorn.conf.py`
- Set `preload_app = False` — each worker now boots independently with its own clean event loop and connection pools.
- Removed the `post_fork` pool disposal hook — no longer needed since workers no longer fork from a preloaded parent.

### `main.py`
- Added `_leader_loop()` — a Redis distributed lock loop. Every worker runs it, but only the holder of key `bg:task:leader` actually starts the singleton background tasks. If the leader worker dies (graceful or SIGKILL), another worker promotes itself automatically.
- Added `redis.asyncio` as a top-level import.
- Lifespan now unconditionally starts only **per-worker** tasks (Redis pub/sub listener, stale-WS cleanup — both operate on local connections). All other background tasks run only in the leader.

## Leader Election Behaviour

| Key | Value |
|---|---|
| Redis key | `bg:task:leader` |
| Lock TTL | 30s (expires if not renewed) |
| Renewal interval | 12s (every worker polls; leader renews) |
| Failover time | ≤ 30s after leader SIGKILL; immediate on graceful shutdown |

On graceful shutdown the leader deletes the lock immediately so a follower promotes within 12s rather than waiting the full TTL.

## Singleton Tasks (leader only)
- Monitoring health check loop (300s interval)
- Metrics collection loop (60s interval)
- Agent status heartbeat checker (60s interval)
- Reconciliation sweeper (60s interval)

## Per-Worker Tasks (all workers)
- Redis pub/sub listener (delivers cross-worker broadcasts to local WebSocket connections)
- Stale customer WebSocket connection cleanup
