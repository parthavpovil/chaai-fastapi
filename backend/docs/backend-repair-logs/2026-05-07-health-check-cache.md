# §9.3 — Health Check: Cache Result + Non-Blocking R2 Check

## Problem

`GET /health` ran two expensive operations on every load-balancer probe:

1. **DB query via `get_db()`** — created a full `AsyncSession`, ran `SELECT 1`,
   tore it down. Load balancers probe every 5–30 s; at 3 Gunicorn workers × 3
   probes/min that's ~9 unnecessary DB round-trips per minute doing nothing
   except consuming a pool connection.

2. **Synchronous `r2.head_bucket()`** — boto3 is blocking I/O. Calling it
   directly from an `async def` handler blocks the entire event loop thread for
   the duration of the HTTP round-trip to Cloudflare (typically 50–200 ms).
   During that window no other request can be processed.

**Severity:** Medium. Under low load, unnoticeable. Under high load or when R2
has latency spikes, the blocking call serializes all other requests behind it.

## Fix

### Result cache (avoids per-probe DB + R2 cost)

Module-level cache with double-checked locking:

```
_HEALTH_CACHE_TTL = 10.0 seconds
_health_cache: dict | None
_health_cache_expires: float
_health_cache_lock: asyncio.Lock
```

Fast path (no lock): if `monotonic() < _health_cache_expires`, return cached.
Slow path (lock): one coroutine refreshes; the rest wait and then use the new
result without running the checks themselves.

Result: DB and R2 are hit at most once every 10 seconds regardless of probe
frequency.

### `engine.connect()` instead of `get_db()`

`get_db()` creates an `AsyncSession` (ORM overhead). For a connectivity probe
all we need is a raw connection and a single statement. Using
`engine.connect()` is lighter and does not allocate a session-level identity map.

### `run_in_executor` for R2

```python
await loop.run_in_executor(
    None,
    functools.partial(r2.head_bucket, Bucket=settings.R2_BUCKET_NAME),
)
```

Offloads the blocking boto3 call to the default thread-pool executor so the
event loop remains free during the network round-trip.

### Per-check response times

Each sub-check now records its own `response_time_ms` so slow dependencies are
immediately visible in the health payload.

## Frontend / Deployment Impact

None — response shape is the same, just with an added `response_time_ms` field
per sub-check. The top-level `response_time_ms` and `status` are unchanged.

## Files Changed

- `main.py` — `_run_health_checks()` helper, cache variables, updated handler

## Testing Checklist

- [ ] Hit `/health` 5× in quick succession — verify only one DB query fires
  (check DB logs or query counter)
- [ ] Verify `X-Response-Time` header on cached responses is < 1 ms
- [ ] Simulate R2 unavailability — verify `storage.status = "unhealthy"` without
  hanging the response (executor timeout kicks in at OS level)
- [ ] After 10 s, verify a fresh probe triggers a real check
