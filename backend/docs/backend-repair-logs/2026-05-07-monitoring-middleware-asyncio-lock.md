# §4.2 — Replace threading.Lock with asyncio.Lock in MonitoringMiddleware

## Problem

`MonitoringMiddleware` used `threading.Lock` to protect its in-memory metrics
dicts. In an asyncio application running on a single OS thread (UvicornWorker),
`threading.Lock.acquire()` is a blocking call. If a coroutine holds the lock
while another coroutine tries to acquire it, the second coroutine blocks the
entire event loop thread — no other requests can make progress until the lock
is released.

While the operations inside the lock were fast enough that this rarely caused
observable stalls, the pattern is semantically wrong and a latency risk under
high concurrency.

**Severity:** Medium. Silent latency regression under load; also signals intent
confusion (sync primitives in async code).

## Root Cause

`self.lock = threading.Lock()` used throughout an `async` middleware class.
All lock-protected blocks used `with self.lock:` (blocking) rather than
`async with self.lock:` (yielding).

## Fix

- Replaced `threading.Lock()` with `asyncio.Lock()`
- Changed all five `with self.lock:` blocks to `async with self.lock:`
- Made `get_metrics()`, `get_recent_requests()`, and `reset_metrics()` async
  (required because `async with` can only appear in a coroutine)
- Removed the now-unused `import threading`
- Updated the single call site in `main.py`:
  `return middleware.get_metrics()` → `return await middleware.get_metrics()`

## Why asyncio.Lock is sufficient here

The entire FastAPI/Uvicorn stack runs on a single event loop thread per process.
Asyncio's cooperative scheduling guarantees that no other coroutine can interrupt
a block of code that contains no `await`. This means the explicit lock is only
needed to protect sequences that span multiple `await` points — which none of
these metrics updates do. `asyncio.Lock` is the correct primitive to express
"yield the event loop while waiting rather than block the OS thread."

## Frontend Impact

None.

## Files Changed

- `app/middleware/monitoring_middleware.py`
- `main.py` (await on `get_metrics()`)
