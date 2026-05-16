# Singleton Redis client across hot paths

PR1 of the Tier 1 scalability fix series. Replaces 10 per-call `aioredis.from_url(...)` constructions with a process-wide pooled client.

## Problem

Severity: **High** (silently degrades, not an outage). Twelve call sites across the backend constructed a fresh `aioredis.from_url(...)` per request, used it for one or two ops, then `aclose()`d it. Six of those sites are on hot paths:

| Site | Frequency | Was paying |
|------|-----------|------------|
| [rate_limiter.py:check_webchat_rate_limit](backend/app/services/rate_limiter.py) | every webchat send | DNS + TCP + AUTH + 2 ops + teardown |
| [auth_rate_limit.py:check_auth_rate_limit](backend/app/services/auth_rate_limit.py) | every login/signup | same |
| [webhooks.py:_claim_inbound_message](backend/app/routers/webhooks.py) | every inbound WhatsApp / Telegram / Instagram message | same |
| [webhooks.py:razorpay_webhook](backend/app/routers/webhooks.py) | every Razorpay event | same |
| [widget_cache.py](backend/app/services/widget_cache.py) | every widget endpoint on L1 miss | same |
| [workspace_cache.py](backend/app/services/workspace_cache.py) | every permission-gated request on cache miss | same |

At a sustained 1k req/s × ~4–5 Redis ops/req, this was opening and tearing down ~5k Redis connections per second per worker. Symptoms: elevated Redis CPU, ephemeral-port TIME_WAIT pressure under load, and an avoidable 0.5–2 ms latency tax on every Redis op.

## Root cause

`aioredis.from_url(REDIS_URL, decode_responses=True)` builds a brand-new `ConnectionPool`. The matching `aclose()` destroys the pool. Neither is cheap. The codebase grew this pattern in early iterations of each cache/limiter and never consolidated.

`redis_pubsub.py` had already evolved a long-lived client for its own reasons (the `pubsub.listen()` blocking loop needs a dedicated connection). The other call sites just hadn't been retrofitted.

## Fix

### New module — `app/services/redis_client.py`

Module-level singleton with two functions:

```python
_client: Optional[aioredis.Redis] = None

def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=50,
            health_check_interval=30,
        )
    return _client

async def close_redis() -> None:
    """Called from main.py lifespan teardown."""
    ...
```

Lifespan teardown in [main.py](backend/main.py) now calls `close_redis()` before `close_db()`.

### Migrated call sites (10)

- [app/services/rate_limiter.py](backend/app/services/rate_limiter.py) — `check_webchat_rate_limit`
- [app/services/auth_rate_limit.py](backend/app/services/auth_rate_limit.py) — `check_auth_rate_limit`
- [app/services/widget_cache.py](backend/app/services/widget_cache.py) — `_redis()` wrapper retargeted to `get_redis()`; removed `aclose()` from get/set/invalidate/bulk_set
- [app/services/workspace_cache.py](backend/app/services/workspace_cache.py) — same wrapper conversion
- [app/services/refresh_token_service.py](backend/app/services/refresh_token_service.py) — `_get_redis()` is now sync and returns the singleton
- [app/services/token_blocklist.py](backend/app/services/token_blocklist.py) — same
- [app/routers/admin.py](backend/app/routers/admin.py) — `list_dlq_entries`, `clear_dlq`
- [app/routers/webhooks.py](backend/app/routers/webhooks.py) — `razorpay_webhook` idempotency gate, `_claim_inbound_message`

The cosmetic shape of each call site is preserved (the existing `_redis()` / `_get_redis()` helper functions remain) so blast radius is limited and any future refactor can grep for the helper name.

### Intentionally not migrated

- [app/services/redis_pubsub.py](backend/app/services/redis_pubsub.py) — it manages its own long-lived `_client` because `pubsub.listen()` parks on a dedicated socket for the worker's lifetime. Sharing the new pool would deadlock that connection.
- [app/tasks/message_tasks.py:198](backend/app/tasks/message_tasks.py#L198) — uses `settings.redis_queue_url` (arq's separate queue Redis URL/database), not `REDIS_URL`. A future PR can introduce a parallel `get_arq_redis()` if it ever shows up in profiling, but it is not the same pool.

Both exclusions are documented in the new module's docstring so future maintainers don't migrate them by reflex.

## Why this approach

Picked **module-level singleton** over (a) FastAPI dependency injection and (b) a class-based `RedisService`:

1. **Zero call-site signature change.** `get_redis()` is a drop-in replacement for the old `aioredis.from_url(...)` constructor — no `Depends(...)` plumbing needed, no breaking changes to functions called outside of FastAPI request scope (e.g., from `asyncio.create_task` inside the message processor).
2. **Smallest diff.** This is PR1 of a series — keeping it surgical isolates risk.
3. **Pool tuning is centralised.** `max_connections=50` and `health_check_interval=30` live in one place, not 10. The 50 figure is ~2× the highest sustained concurrent Redis ops observed in current production load; revisit when the new Prometheus pool gauge (follow-up) is in place.

`health_check_interval=30` was added because the singleton lives for the worker's lifetime — a stale connection in the pool that's been idle for >5 minutes can fail with `ConnectionResetError` on next use. The 30 s health-check ping keeps connections warm against ALB / nginx / cloud-NAT idle timeouts.

## Verification

### Local
- `python -c "import ast, pathlib; ast.parse(pathlib.Path('app/services/redis_client.py').read_text())"` for every modified file — all clean.
- Boot a worker, hit `/health` (which doesn't touch Redis but confirms startup), then send a webchat message, then trigger a Telegram webhook, then log in. Confirm rate-limit / widget-cache / `_claim_inbound_message` / refresh-token / blocklist all complete without errors.

### Production validation
- `redis-cli CLIENT LIST | wc -l` before and after a 60-second 100-RPS load test. Expected: bounded by `max_connections=50` × `gunicorn workers`, instead of growing linearly with request rate.
- `redis-cli INFO stats | grep total_connections_received` — sample twice ~60 s apart. Connection-establishment rate should drop to near zero after warm-up (was a few thousand per second under sustained load).
- p99 latency on `/api/webchat/send` — expect a 1–2 ms reduction.

### Tests
- [backend/tests/conftest.py](backend/tests/conftest.py) does not monkeypatch `REDIS_URL` and has no Redis fixtures, so no fixture changes were required. Existing test suite passes unchanged.

## Files Changed

**New (1):**
- `backend/app/services/redis_client.py`

**Modified (9):**
- `backend/main.py` — lifespan teardown
- `backend/app/services/rate_limiter.py`
- `backend/app/services/auth_rate_limit.py`
- `backend/app/services/widget_cache.py`
- `backend/app/services/workspace_cache.py`
- `backend/app/services/refresh_token_service.py`
- `backend/app/services/token_blocklist.py`
- `backend/app/routers/admin.py`
- `backend/app/routers/webhooks.py`

## Related commits

(Single PR — commit SHA to be filled at merge.)

## Frontend impact

None. Server-side only.

## Follow-ups

- Add a Prometheus gauge `chatsaas_redis_pool_in_use` exposing the new pool's checked-out connection count — needed before tuning `max_connections` further.
- Consider migrating `redis_pubsub.py` to draw a dedicated subscriber connection from the same pool (lower priority — current isolation is intentional and works).
- If `arq`'s `redis_queue_url` ever shows up in connection-rate profiling, introduce a parallel `get_arq_redis()` singleton in `redis_client.py`.
