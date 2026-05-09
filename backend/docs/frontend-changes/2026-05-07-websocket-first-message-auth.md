# WebSocket Auth: Token Moved from Query String to First Message

## Why This Changed

JWT tokens and session tokens in WebSocket URLs appear verbatim in server
access logs, CDN logs, and browser history. Moving them to the first WebSocket
message keeps them off the wire in URLs.

## What Changed

### Agent / Dashboard WebSocket

**Old URL:**
```
wss://api.example.com/ws/<workspace_id>?token=<jwt>
```

**New URL + first message:**
```js
const ws = new WebSocket(`wss://api.example.com/ws/${workspaceId}`)

ws.onopen = () => {
  ws.send(JSON.stringify({ type: "auth", token: accessToken }))
}
```

The server waits up to 10 seconds for this message. If it doesn't arrive,
it closes the connection with code 4001.

### Customer Webchat WebSocket

**Old URL:**
```
wss://api.example.com/ws/webchat/<workspace_id>?widget_id=<id>&session_token=<token>
```

**New URL + first message:**
```js
// widget_id stays in the query string (it's a public identifier)
const ws = new WebSocket(
  `wss://api.example.com/ws/webchat/${workspaceId}?widget_id=${widgetId}`
)

ws.onopen = () => {
  ws.send(JSON.stringify({ type: "auth", session_token: sessionToken }))
}
```

## Auth Response

After a successful auth message, the server sends `connection_established`
exactly as before:
```json
{
  "type": "connection_established",
  "connection_id": "...",
  "workspace_id": "...",
  "connected_at": "..."
}
```

If auth fails (invalid token, wrong message format, or 10-second timeout),
the server closes with WebSocket code **4001**.

## Error Handling

```js
ws.onclose = (event) => {
  if (event.code === 4001) {
    // Auth failed — redirect to login or retry with fresh token
  }
}
```

## Migration Checklist

- [ ] Remove `?token=...` from the agent WebSocket URL
- [ ] Send `{type:"auth", token}` in the `onopen` handler
- [ ] Remove `&session_token=...` from the webchat widget URL
- [ ] Send `{type:"auth", session_token}` in the widget's `onopen` handler
- [ ] Handle close code 4001 in both `onclose` handlers
