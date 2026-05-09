# §5.3 — WebSocket Credentials Moved from Query String to First Message

## Problem

Both WebSocket endpoints passed secrets in query parameters:

- `/ws/{workspace_id}?token=<jwt>` — agent JWT in URL
- `/ws/webchat/{workspace_id}?widget_id=...&session_token=<token>` — session token in URL

Query parameters appear verbatim in:
- Nginx / CloudFlare / CDN access logs
- Browser history
- Browser developer tools "Network" tab URLs
- Proxy server logs
- Any structured logging that records the full request URL

An attacker with read access to access logs — or a junior developer accidentally
sharing a log snippet — would capture live JWTs or customer session tokens with
no other effort required.

**Severity:** HIGH for session security. Tokens in URLs are effectively
cleartext credentials in logs.

## Fix

### Connection handshake

Both endpoints now follow the first-message auth pattern:

1. Client calls `connect(wss://host/ws/...)`  — no credentials in URL
2. Server calls `websocket.accept()` immediately (TCP upgrade completes)
3. Server waits up to **10 seconds** for the first message
4. Client sends `{"type": "auth", "token": "<jwt>"}` (agent) or
   `{"type": "auth", "session_token": "<token>"}` (customer)
5. Server validates credentials; if invalid → close 4001, if timeout → close 4001
6. Server calls `websocket_manager.connect(..., already_accepted=True)` to
   register the connection and send `connection_established`

### `websocket_manager.py`

Both `WebSocketManager.connect()` and `CustomerWebSocketManager.connect()`
gained an `already_accepted: bool = False` parameter. When `True`, the internal
`await websocket.accept()` call is skipped (the router has already accepted).

### Agent WS (`/ws/{workspace_id}`)

Removed: `token: str = Query(...)`  
Added: `_AUTH_TIMEOUT = 10.0`, first-message read, token extracted from
`{"type": "auth", "token": "..."}`.

### Customer webchat WS (`/ws/webchat/{workspace_id}`)

Removed: `session_token: str = Query(...)`  
Kept: `widget_id: str = Query(...)` — this is a **public** identifier embedded
in the widget's `<script>` tag and contains no secret.  
Added: `session_token` extracted from first message
`{"type": "auth", "session_token": "..."}`.

## Frontend Impact

See `docs/frontend-changes/2026-05-07-websocket-first-message-auth.md`.
Both WebSocket connection calls are a breaking change.

## Files Changed

- `app/routers/websocket.py`
- `app/routers/websocket_webchat.py`
- `app/services/websocket_manager.py`

## Testing Checklist

- [ ] Connect to `/ws/{workspace_id}` without sending auth → verify 4001 after 10 s
- [ ] Connect and send `{"type":"auth","token":"<valid_jwt>"}` → verify `connection_established`
- [ ] Connect and send wrong token → verify close 4001
- [ ] Customer widget: connect, send `{"type":"auth","session_token":"<valid>"}` → verify push events arrive
- [ ] Verify Nginx access log: `/ws/{workspace_id}` URL contains no token
