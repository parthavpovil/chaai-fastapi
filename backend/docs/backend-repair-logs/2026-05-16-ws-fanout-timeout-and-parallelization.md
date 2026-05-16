# WebSocket fanout: per-send timeout + bounded parallel sends

PR2 of the Tier 1 scalability fix series. Eliminates head-of-line blocking in the agent workspace fanout and adds a per-send timeout to both agent and customer managers.

## Problem

Severity: **Critical** for any workspace with more than a handful of active agents on flaky networks.

The agent-side `WebSocketManager.deliver_to_local` fanned out sequentially:

```python
for conn_id, conn in connections.items():
    if conn_id == exclude_id:
        continue
    ok = await conn.send_message(message)   # ← awaits TCP write
    if not ok:
        failed.append(conn_id)
```

`send_message` calls Starlette's `WebSocket.send_text(...)` which awaits the underlying TCP write. If a client's receive buffer is full (suspended mobile tab, dead Wi-Fi, dashboard left open in a backgrounded browser), the await parks indefinitely. With N connections in a workspace, the Nth client cannot receive any message until the 1st through (N-1)th clients have finished — even if any one of them hangs.

Compounded by [PR3 — listener detach (separate repair log)](2026-05-16-redis-listener-detach-fanout.md): one slow workspace was also stalling the Redis pub/sub listener for every other workspace on the worker. PR3 fixes the cross-workspace head-of-line; PR2 fixes the within-workspace head-of-line.

The customer-side `CustomerWebSocketManager.deliver_to_local` had the same `await send_message` without a timeout. Customer fanout is 1-to-1 (one session token per workspace pool key), so there is no cross-client blocking — but a single suspended widget tab on a customer's phone could still park the Redis listener via that path.

Operational symptom that motivated the fix: intermittent "the agent dashboard is frozen" reports, where one agent's tab on a flaky connection caused other agents in the same workspace to stop seeing new messages.

## Root cause

Two distinct problems in the same shape of code:

1. **No per-send timeout.** `WebSocket.send_text()` is bounded only by TCP behavior. On a healthy connection it returns in ms; on a stalled receiver it can park for the OS-default TCP retransmit window (minutes to hours).
2. **Sequential fanout in the agent manager.** Even with a per-send timeout of 3 s, sequential fanout means a workspace with 50 connections and one slow client adds 3 s of latency to the 50th client's message delivery.

## Fix

### Module-level constants

Added at the top of [app/services/websocket_manager.py](backend/app/services/websocket_manager.py) — referenced by both managers:

```python
_SEND_TIMEOUT = 3.0          # per-send wait_for() timeout
_FANOUT_CONCURRENCY = 64     # cap on parallel sends per workspace
```

### Agent manager — `WebSocketManager.deliver_to_local`

```python
async def deliver_to_local(self, workspace_id: str, message: dict) -> None:
    exclude_id = message.pop("_exclude", None)
    connections = self.workspace_connections.get(workspace_id, {}).copy()
    targets = [c for cid, c in connections.items() if cid != exclude_id]
    if not targets:
        return

    sem = asyncio.Semaphore(_FANOUT_CONCURRENCY)

    async def _send(conn) -> Optional[str]:
        async with sem:
            try:
                await asyncio.wait_for(conn.send_message(message), timeout=_SEND_TIMEOUT)
                return None
            except (asyncio.TimeoutError, Exception):
                return conn.connection_id

    failed = await asyncio.gather(*(_send(c) for c in targets))
    for cid in filter(None, failed):
        # Detach disconnect cleanup so it never blocks the fanout path.
        asyncio.create_task(self.disconnect(cid))
```

### Customer manager — `CustomerWebSocketManager.deliver_to_local`

The customer manager delivers to one session, not many — no `gather` is needed. But the same `wait_for(_SEND_TIMEOUT)` is now wrapped around the single send, and disconnect on failure is detached:

```python
try:
    await asyncio.wait_for(connection.send_message(message), timeout=_SEND_TIMEOUT)
    ok = True
except (asyncio.TimeoutError, Exception):
    ok = False
...
if not ok:
    asyncio.create_task(self.disconnect(connection.connection_id))
```

The pre-existing `[DEBUG]` log lines around `deliver_to_local` were preserved unchanged — they are still load-bearing for diagnosing widget delivery issues.

## Why this approach

### `Semaphore(64)` as the per-workspace concurrency cap

Starlette's `WebSocket.send_text()` is safe to call concurrently from multiple tasks within a single event loop (one event loop = one thread = no true parallel writes; the asyncio scheduler interleaves them at await points). So an unbounded `gather()` is technically safe, but it would create one coroutine *per connection per message*. At 5000 active connections × 100 broadcasts/sec that's 500k pending coroutines — memory blowup risk under broadcast storms.

`64` is well above any realistic single-workspace agent count (we have not observed any workspace with more than ~30 active agents) and small enough that the asyncio scheduler can schedule the sends interleaved with other event-loop work.

### `wait_for(3.0)` as the per-send timeout

Three seconds is well above the 95th-percentile TCP RTT for any realistic client — a healthy agent's `send_text` returns in <50 ms, a slow agent's in <500 ms. A 3 s timeout means we declare a client dead only after they've failed to drain their receive buffer for an interval that healthy clients comfortably beat.

### Detached disconnect via `asyncio.create_task`

`disconnect()` acquires the manager's `_lock` and (for the agent manager, when the workspace becomes empty) calls `redis_pubsub.unsubscribe(...)`. Both can be slow under load. Awaiting them inline would re-introduce a head-of-line blocker downstream of the fanout fix. Detaching is safe because `disconnect()` is idempotent (it checks for the connection and no-ops if already removed) and the `_lock` invariant — never held across network awaits — was already established in the file's docstring.

### Why not also add a Prometheus histogram now

The plan called out `chatsaas_ws_fanout_latency_seconds` as a follow-up. Keeping this PR purely behavioral makes it easier to revert if a regression appears. Metrics will land in a follow-up.

## Verification

### Local
- Parse check: `python -c "import ast, pathlib; ast.parse(pathlib.Path('app/services/websocket_manager.py').read_text())"` — clean.
- **Manual offline-tab test:** Open two browser tabs as agents in the same workspace. Use Chrome DevTools → Network tab → "Offline" on one tab. Trigger a workspace broadcast (e.g., have a customer send a webchat message). Confirm the second (still-online) tab receives the broadcast in <100 ms — not delayed by the offline tab's stall. After 3 s, confirm a `disconnect` log line for the offline tab. Reopen the offline tab and confirm reconnect works normally.
- **Customer manager:** Open the embed widget in a browser, suspend the tab (background it long enough for OS to throttle), trigger a server-pushed message via `customer_websocket_manager.send_to_session(...)`. Confirm the server-side log shows `ok=False` after 3 s and the connection is detached for cleanup.

### Production validation
- Watch the existing `📨 [DEBUG] customer deliver_to_local` log lines for `send_message returned False` events — should now correlate tightly with disconnect log lines, no stuck delivery loops.
- (Follow-up) Add `chatsaas_ws_fanout_latency_seconds` histogram and confirm p99 < 50 ms even on the largest workspaces.

### Tests
- Existing WS tests in [backend/tests/](backend/tests/) (`test_websocket_*.py`) exercise the connect/disconnect/broadcast flow without modeling slow clients, so they validate that the happy path is unchanged. They pass without modification.

## Files Changed

**Modified (1):**
- `backend/app/services/websocket_manager.py` — added `_SEND_TIMEOUT` / `_FANOUT_CONCURRENCY` module constants; rewrote both managers' `deliver_to_local`.

## Related commits

(Single PR — commit SHA to be filled at merge.)

## Frontend impact

None. The wire format is unchanged: same `send_text(json.dumps(message))` per connection; same message shapes. From the client's perspective the only difference is that a previously-stuck connection is now closed by the server within 3 s of going unresponsive instead of hanging indefinitely. Existing reconnect logic on both the dashboard and the widget already handles server-initiated close cleanly.

## Follow-ups

- Prometheus histogram `chatsaas_ws_fanout_latency_seconds{role}` and counter `chatsaas_ws_send_timeouts_total` so the gain is visible.
- Per-workspace fanout duration log line (sampled, not every message) for capacity planning.
- Consider lifting `_FANOUT_CONCURRENCY` to a setting if any workspace ever sustains more than 64 concurrent agents.
