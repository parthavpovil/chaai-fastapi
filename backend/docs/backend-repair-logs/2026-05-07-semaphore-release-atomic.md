# §8.2 — Atomic Semaphore Release (Fix GET+DECR Race and Log Level)

## Problem

`_release_semaphore` decremented the per-workspace concurrency counter using a
non-atomic GET + conditional DECR:

```python
val = await redis_client.get(key)
if val is not None and int(val) > 0:
    await redis_client.decr(key)
```

### Race condition (correctness bug)

Two workers finishing concurrently could both read the same positive value,
both pass the `> 0` guard, and both issue `DECR` — driving the counter below
zero.

Once negative, the `_ACQUIRE_LUA` script compares `cur >= limit` with a
negative `cur`, which is always false, so every subsequent acquire succeeds
regardless of how many jobs are already running. The per-workspace concurrency
cap is silently broken for all future requests until the key expires (up to
`_SEMAPHORE_TTL` = 300 s).

### Severity

HIGH for paid workspaces — their concurrency limits exist to bound LLM API
spend. A negative counter lets the workspace run unlimited parallel jobs,
potentially exhausting the AI provider quota or causing rate-limit errors.

### Secondary issue: log level too low

Release failures (Redis unavailable, network error) were logged as `WARNING`.
A leaked slot blocks ALL new messages for the workspace for up to 300 s.
That warrants `ERROR`.

## Fix

Added `_RELEASE_LUA` — a Lua script that atomically reads and conditionally
decrements in a single Redis round trip:

```lua
local val = tonumber(redis.call('GET', KEYS[1]) or '0')
if val > 0 then
    redis.call('DECR', KEYS[1])
end
return val
```

Because Lua scripts in Redis execute atomically, no other command can execute
between the read and the decrement. The counter can never go below zero.

`_release_semaphore` now calls `redis_client.eval(_RELEASE_LUA, 1, key)`.

The exception handler is intentionally kept (swallowing its own errors) — a
release failure must not replace the original job exception propagating through
the outer `finally` block. The TTL still provides the safety net. Log level
raised from `WARNING` to `ERROR`.

## Files Changed

- `app/tasks/message_tasks.py` — `_RELEASE_LUA` constant, `_release_semaphore` body

## Frontend Impact

None.

## Testing Checklist

- [ ] Two workers finish simultaneously for the same workspace — verify counter
  reaches 0 (not -1) using `redis-cli GET ws_concurrency:<id>`
- [ ] After both workers finish, a new job acquires the semaphore normally
- [ ] Simulate Redis error on release — verify ERROR log appears and original
  job result is still correct (exception not masked)
