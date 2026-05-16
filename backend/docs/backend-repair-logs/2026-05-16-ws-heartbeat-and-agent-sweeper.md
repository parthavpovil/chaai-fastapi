# Server-initiated WS heartbeat + agent stale-connection sweeper

PR4 of the Tier 1 scalability fix series. Closes two related lifecycle gaps on the WebSocket plane: the agent sweeper that was defined but never started, and the absence of any server-initiated heartbeat on either WS manager.

## Problem

Severity: **High** — slow-burn memory leak + silent connectivity loss for idle agents.

### Gap 1 — agent sweeper never started

The customer-side stale-connection sweeper was wired in [main.py](backend/main.py):

```python
asyncio.create_task(websocket_webchat.cleanup_stale_customer_connections())
```

The agent-side equivalent at [app/routers/websocket.py:499-513](backend/app/routers/websocket.py#L499) was defined but never invoked:

```python
async def cleanup_stale_connections():
    while True:
        try:
            cleanup_count = await websocket_manager.cleanup_stale_connections(max_idle_minutes=30)
            ...
        await asyncio.sleep(300)
```

Result: an agent who closes their laptop (or whose browser is killed by the OS) without a WS close frame leaks an entry in `WebSocketManager.workspace_connections` and `WebSocketManager.connections` until the OS TCP socket times out — minutes to hours depending on kernel. Over a week of normal operations, this walks worker memory upward and eventually triggers an OOM.

### Gap 2 — no server-initiated heartbeat

Both managers' existing ping logic was client-initiated: the client sends `{"type": "ping"}`, the server calls `handle_ping(connection_id)` and sends back a pong, updating `last_ping` along the way. There was no path by which the server proactively pinged clients.

Cloud LBs (AWS ALB defaults to 60 s idle timeout; nginx `proxy_read_timeout` typically 60–300 s) silently drop idle TCP connections. With no server ping:
- The WS stays half-open server-side — the LB has closed its half, the server hasn't been told.
- The client believes it's connected; their next outbound message succeeds locally but is dropped at the LB.
- The agent reports "I sent the reply but it never went through" while the connection looks healthy server-side.

This is a well-known operability disaster for WS at scale and has bitten chaai's dashboard users intermittently.

## Root cause

Two independent one-line / small omissions in the lifecycle wiring:

1. `cleanup_stale_connections` for agents was added at some point but the corresponding `asyncio.create_task(...)` in `main.py` lifespan never landed.
2. The managers had `handle_ping` (client-initiated) but no symmetric server-initiated loop. Building one wasn't necessary while the dashboard was sending its own pings; the gap became visible once mobile agents started disconnecting silently through ALB.

## Fix

### Constants

Added at the top of [app/services/websocket_manager.py](backend/app/services/websocket_manager.py) alongside the fanout constants:

```python
_HEARTBEAT_INTERVAL = 30   # seconds between server-initiated pings
_HEARTBEAT_TIMEOUT = 10    # max wait for client pong before disconnecting
```

30 s is comfortably inside the 60 s ALB default idle window. 10 s pong-timeout is generous (a healthy client returns a pong in <100 ms) but small enough that a dead client is detected within 40 s end-to-end.

### Heartbeat — agent manager

```python
async def heartbeat_loop(self) -> None:
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            for conn in list(self.connections.values()):
                asyncio.create_task(self._ping_or_drop(conn))
        except Exception as e:
            logger.error(f"agent heartbeat loop error: {e}", exc_info=True)

async def _ping_or_drop(self, conn) -> None:
    try:
        await asyncio.wait_for(conn.send_ping(), timeout=_HEARTBEAT_TIMEOUT)
    except Exception:
        await self.disconnect(conn.connection_id)
```

Per-connection ping is detached into its own task so one stalled client never stalls the heartbeat loop.

### Heartbeat — customer manager

The agent-side `WebSocketConnection` already had `send_ping`. The customer-side `CustomerWebSocketConnection` did not — added it as a thin mirror of the agent implementation:

```python
async def send_ping(self) -> bool:
    try:
        return await self.send_message({
            "type": "ping",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        return False
```

Then a matching `heartbeat_loop` and `_ping_or_drop` on `CustomerWebSocketManager` iterating `self.connections_by_id`.

### Lifespan wiring — main.py

```python
# Agent-side stale-connection sweeper. Mirrors the customer sweeper above.
from app.routers.websocket import cleanup_stale_connections as cleanup_stale_agent_connections
asyncio.create_task(cleanup_stale_agent_connections())

# Server-initiated WS heartbeats for both managers.
asyncio.create_task(websocket_manager.heartbeat_loop())
asyncio.create_task(customer_websocket_manager.heartbeat_loop())
```

The sweeper and heartbeat are independent and intentionally overlap:

- **Heartbeat** catches half-open sockets (LB silently dropped, client crashed without close frame). Detects in `_HEARTBEAT_INTERVAL + _HEARTBEAT_TIMEOUT` ≈ 40 s worst case.
- **Sweeper** catches the case where the heartbeat *succeeds* but the connection has otherwise gone unused for 30 minutes. Belt-and-braces against any bug that lets a dead connection's `last_ping` get updated without real activity.

## Why this approach

### Per-connection task per heartbeat tick

The naïve form (`for conn in connections: await self._ping_or_drop(conn)`) would serialize all pings on the heartbeat task — re-introducing exactly the head-of-line shape that PR2 just fixed for fanout. Detaching keeps the loop responsive even if a few clients are slow.

### 30 s / 10 s timing

- `_HEARTBEAT_INTERVAL = 30`: half the default ALB idle (60 s) — comfortable margin against LB-side timeout.
- `_HEARTBEAT_TIMEOUT = 10`: healthy clients return a pong in <100 ms; a 10 s window declares a client dead only after they've failed by 100×.

These could be tuned higher to reduce ping overhead at scale, but 30 s × N connections × ~50 bytes per ping is negligible (<5 KB/s even at 1000 connections per worker).

### `send_ping` returns from `send_message`, not raw `send_text`

Reuses the existing wrapper so the `_lock` / exception-logging behavior is consistent with all other server-initiated sends.

### Frontend compatibility note

Both the dashboard and the widget already handle `{"type": "ping"}` (they currently *send* such messages and expect pongs). They will now also *receive* server-initiated `ping` messages. Behavior to verify before merge:

- If the frontend silently ignores unknown-purpose pings → OK, ship as-is.
- If the frontend errors on a message with `type=ping` it didn't expect → coordinate a frontend release first that either no-ops or replies with a pong.

If a frontend release is needed first, change the server message `type` to `server_ping` to avoid colliding with the existing client-originated `ping`. The dashboard's WS handler is at `frontend/src/.../useWebSocket.tsx` (verify before merging this PR).

## Verification

### Local
- Parse check on `main.py` and `app/services/websocket_manager.py` — clean.
- **Sweeper test:** Connect an agent WS, force-quit the browser (no clean close). Within 30 minutes (or temporarily lower `max_idle_minutes`) confirm the `disconnect` log fires and `WebSocketManager.connections` no longer contains the connection.
- **Heartbeat test:** Connect an agent WS, leave the tab idle. In Chrome DevTools → Network → WS → Frames pane, confirm a `{"type":"ping"}` server-pushed frame appears every 30 s. The connection survives a 60 s+ ALB idle window.
- **Heartbeat detects dead client:** Connect, then close the underlying TCP without sending a WS close frame (e.g. firewall block). Within `_HEARTBEAT_INTERVAL + _HEARTBEAT_TIMEOUT` ≈ 40 s confirm a `disconnect` log line.

### Production validation
- Watch the rate of unscheduled disconnects post-deploy — expect a small bump in the first 30 s after each LB-killed connection is detected, then steady state.
- (Follow-up) Prometheus gauge `chatsaas_ws_connections_total{role}` so the connection-count walk-up shape (or lack of it) is visible.

### Tests
- Existing WS tests in [backend/tests/](backend/tests/) don't model server-pings; they pass unchanged.

## Files Changed

**Modified (2):**
- `backend/main.py` — wired agent sweeper + both heartbeat loops in lifespan.
- `backend/app/services/websocket_manager.py` — `_HEARTBEAT_INTERVAL` / `_HEARTBEAT_TIMEOUT` constants; `CustomerWebSocketConnection.send_ping`; `heartbeat_loop` + `_ping_or_drop` on both managers.

## Related commits

(Single PR — commit SHA to be filled at merge.)

## Frontend impact

Verify dashboard and widget WS handlers tolerate (or reply to) an unsolicited `{"type":"ping"}` from the server. Both already handle outbound pings + inbound pongs; the inverse should be either silent-ignore or pong-reply. Coordinate a small frontend release if either errors on unknown message types. Otherwise no behavioral change visible to users.

## Follow-ups

- Prometheus gauge `chatsaas_ws_connections_total{role=agent|customer}` exposed via a custom collector — needed to make the leak-prevention visible over weeks.
- Counter `chatsaas_ws_heartbeat_dropped_total{role}` to track how many connections the heartbeat is actually catching (sanity check that it's worth the network overhead).
- Consider client-side declaration of a `connection_id` (UUID minted client-side) so reconnect-through-different-worker doesn't lose the `_exclude` self-skip — flagged in audit §1.11 as Low severity, can defer.
