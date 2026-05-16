# Detach Redis pub/sub listener from WebSocket fanout

PR3 of the Tier 1 scalability fix series. The Redis pub/sub listener no longer awaits per-workspace fanout inline; fanouts are dispatched as bounded background tasks so a slow workspace never stalls cross-workspace delivery.

## Problem

Severity: **Critical** — combined with [PR2 — WS fanout fix](2026-05-16-ws-fanout-timeout-and-parallelization.md), this was the second half of the head-of-line block on the WS plane.

Before this fix, `_redis_dispatch` in [main.py](backend/main.py) awaited `deliver_to_local(...)` inline:

```python
async def _redis_dispatch(channel: str, message: dict) -> None:
    if channel.startswith("ws:agent:"):
        workspace_id = channel[len("ws:agent:"):]
        await websocket_manager.deliver_to_local(workspace_id, message)   # ← inline await
    elif channel.startswith("ws:customer:"):
        ...
```

The Redis listener at [app/services/redis_pubsub.py](backend/app/services/redis_pubsub.py) is a single coroutine that calls the dispatch callback in a loop. So one slow workspace's fanout was the only thing the listener was doing — every other workspace's pub/sub events queued behind it on the same task.

PR2 fixed within-workspace head-of-line (one slow client doesn't block other clients in the same workspace). PR3 fixes the equivalent across workspaces (one slow workspace doesn't block other workspaces on the worker).

## Root cause

The pub/sub listener is the worker's single consumer of WS events. Doing real work — including waiting on TCP writes to clients via `send_text` — inside that consumer serializes everything that consumer is responsible for.

After PR2 the per-fanout latency is bounded (≤ `_SEND_TIMEOUT = 3.0` seconds even in the worst case), but 3 s of stall on every fanout for one slow client would still add 3 s to every other workspace's event delivery on that worker.

## Fix

Replaced the inline `await` with `asyncio.create_task`, guarded by a per-process inflight counter that drops with a logged error if the cap is exceeded.

```python
_MAX_INFLIGHT_FANOUT = 2000
_inflight_fanout = 0

async def _fanout(target, workspace_id: str, message: dict) -> None:
    nonlocal _inflight_fanout
    try:
        await target(workspace_id, message)
    finally:
        _inflight_fanout -= 1

async def _redis_dispatch(channel: str, message: dict) -> None:
    nonlocal _inflight_fanout
    if _inflight_fanout >= _MAX_INFLIGHT_FANOUT:
        logger.error("ws fanout inflight cap hit (%d) — dropping channel=%s",
                     _inflight_fanout, channel)
        return
    if channel.startswith("ws:agent:"):
        workspace_id = channel[len("ws:agent:"):]
        _inflight_fanout += 1
        asyncio.create_task(_fanout(websocket_manager.deliver_to_local, workspace_id, message))
    elif channel.startswith("ws:customer:"):
        workspace_id = channel[len("ws:customer:"):]
        _inflight_fanout += 1
        asyncio.create_task(_fanout(customer_websocket_manager.deliver_to_local, workspace_id, message))
```

The counter is a `nonlocal` inside the lifespan closure so it's per-worker (not shared across processes). The `try/finally` in `_fanout` guarantees decrement even when the underlying `deliver_to_local` raises.

## Why this approach

### `asyncio.create_task` over `asyncio.Queue + worker pool`

The audit's original suggestion was an `asyncio.Queue(maxsize=10000)` plus a dispatcher worker coroutine. Plain `create_task` with a counter is simpler and equivalent under bounding:

- The Queue + worker pattern adds a permanent producer/consumer relationship (one more long-lived coroutine) for no observable benefit when the per-fanout work is already bounded.
- The counter-based approach has the same back-pressure shape (drop above a cap) with one less moving part.
- If we ever need *fair* scheduling across workspaces (e.g. round-robin), the Queue pattern would be the natural place to add it. We don't need that yet.

### Per-process counter, not per-workspace

We could bound per-workspace (e.g. max 50 inflight fanouts per workspace ID). That's a more sophisticated form of fairness but requires a `Counter[str]` keyed by workspace_id with cleanup logic. Per-process is simpler and adequate today: under realistic load the cap is never hit by a single workspace.

If observation shows one workspace consuming a disproportionate share of inflight slots, per-workspace bounding can come as a follow-up.

### Cap of 2000

Fanout tasks in flight ≈ workspaces actively receiving messages × average fanout duration (s) × messages/s. Under sustained 100 msg/s/workspace × 50 workspaces × 50 ms average fanout ≈ 250 inflight. The 2000 cap is ~8× that — wide enough to absorb realistic spikes, narrow enough to bound memory under a true pub/sub storm.

The drop behavior is logged at ERROR level so an alert can be wired on it (recommended follow-up).

## Verification

### Local
- Parse check on [main.py](backend/main.py) — clean.
- **Cross-workspace isolation test (manual):** Inject a temporary `await asyncio.sleep(0.5)` at the top of `WebSocketManager.deliver_to_local`. Send broadcasts to two different workspaces nearly simultaneously via `redis-cli PUBLISH ws:agent:A '{...}'` and `PUBLISH ws:agent:B '{...}'`. Confirm both fanouts complete in ~500 ms (parallel), not ~1000 ms (serial). Remove the temporary sleep before commit.
- **Cap-hit log test:** Temporarily lower `_MAX_INFLIGHT_FANOUT` to `5`, then burst 50 publishes. Confirm the "ws fanout inflight cap hit" error logs fire and the listener stays responsive for new publishes after the cap clears.

### Production validation
- Watch `_inflight_fanout` indirectly via process memory and tail latency — should be stable at low double-digits under normal load.
- (Follow-up) Prometheus gauge `chatsaas_ws_dispatch_inflight` and alert on sustained > 1000.

### Tests
- The existing pub/sub plumbing isn't directly unit-tested (it relies on a live Redis), but the [backend/tests/test_websocket_*](backend/tests/) suite exercises connect/broadcast end-to-end via the manager API. They pass without modification because the public surface of `_redis_dispatch` is unchanged.

## Files Changed

**Modified (1):**
- `backend/main.py` — `_redis_dispatch` now creates background tasks with bounded inflight tracking.

## Related commits

(Single PR — commit SHA to be filled at merge.)

## Frontend impact

None. The wire format and message ordering guarantees are unchanged (and pub/sub never guaranteed strict cross-workspace ordering anyway).

## Follow-ups

- Prometheus gauge `chatsaas_ws_dispatch_inflight` exposed from a thin metrics callback that reads `_inflight_fanout`. Alert if sustained > 1000 for > 1 minute.
- Counter `chatsaas_ws_dispatch_dropped_total{reason="inflight_cap"}` to make cap-hits visible without grepping logs.
- If one workspace is ever observed dominating the inflight count, add per-workspace bounding (see "Why this approach" above).
