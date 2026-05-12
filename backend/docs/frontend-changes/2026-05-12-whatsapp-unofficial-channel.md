# Unofficial WhatsApp Channel — Frontend API Guide

**Date:** 2026-05-12  
**Backend change:** `whatsapp_unofficial` channel type added  
**Affected area:** Channel settings / integrations page

---

## Overview

A new channel type `"whatsapp_unofficial"` is now supported. It connects to a self-hosted Baileys (WhatsApp Web) gateway instead of the official Meta Cloud API. From the frontend's perspective it follows the same channel CRUD pattern as Telegram or official WhatsApp, with a different credential set and a QR-code onboarding step after creation.

---

## 1. Create Channel

### Request

```
POST /api/channels/
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "channel_type": "whatsapp_unofficial",
  "name": "WhatsApp (Unofficial)",
  "credentials": {
    "tenant_id": "workspace-abc-123"
  },
  "is_active": true
}
```

#### Credential fields

| Field | Type | Description |
|---|---|---|
| `tenant_id` | string | Any unique identifier for this workspace's gateway session. Recommend using the workspace ID or a UUID. |

> `gateway_url`, `gateway_api_key`, and `webhook_secret` are configured as server-side environment variables (`WHATSAPP_GATEWAY_URL`, `WHATSAPP_GATEWAY_API_KEY`, `WHATSAPP_WEBHOOK_SECRET`). The frontend does not need to supply them.

> **Note:** During channel creation the backend pings `GET {gateway_url}/health` to verify the gateway is reachable. If the gateway is offline the request fails with `400`.

---

### Success Response — `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "channel_type": "whatsapp_unofficial",
  "name": "WhatsApp (Unofficial)",
  "is_active": true,
  "widget_id": null,
  "platform_info": {
    "valid": true,
    "tenant_id": "workspace-abc-123",
    "gateway_url": "http://localhost:3000",
    "platform": "whatsapp_unofficial"
  },
  "created_at": "2026-05-12T10:30:00.000000+00:00",
  "updated_at": "2026-05-12T10:30:00.000000+00:00"
}
```

> `platform_info` is safe to display — it never contains the `gateway_api_key` or `webhook_secret`.

---

### Error Responses

#### `400` — Gateway unreachable or missing fields
```json
{
  "detail": "Channel validation failed: Cannot reach WhatsApp gateway at http://localhost:3000: ..."
}
```
```json
{
  "detail": "Channel validation failed: gateway_api_key is required for whatsapp_unofficial channel"
}
```

#### `409` — Channel already exists for this workspace
```json
{
  "detail": "A whatsapp_unofficial channel already exists for this workspace"
}
```

#### `402` — Workspace channel limit reached
```json
{
  "detail": "Channel limit reached for your plan"
}
```

---

## 2. List Channels

### Request

```
GET /api/channels/
Authorization: Bearer <access_token>
```

### Response — `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "channel_type": "whatsapp_unofficial",
    "name": "Whatsapp_unofficial Channel",
    "is_active": true,
    "widget_id": null,
    "platform_info": {},
    "created_at": "2026-05-12T10:30:00.000000+00:00",
    "updated_at": "2026-05-12T10:30:00.000000+00:00"
  }
]
```

> `platform_info` is `{}` in list responses for non-webchat channels. Use the single-channel GET to get full details.

---

## 3. Get Channel by ID

### Request

```
GET /api/channels/{channel_id}
Authorization: Bearer <access_token>
```

### Response — `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "channel_type": "whatsapp_unofficial",
  "name": "Whatsapp_unofficial Channel",
  "is_active": true,
  "widget_id": null,
  "platform_info": {},
  "created_at": "2026-05-12T10:30:00.000000+00:00",
  "updated_at": "2026-05-12T10:30:00.000000+00:00"
}
```

---

## 4. Update Channel

### Request

```
PUT /api/channels/{channel_id}
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "name": "WhatsApp Business (Unofficial)",
  "is_active": false
}
```

To update the tenant ID:
```json
{
  "credentials": {
    "tenant_id": "workspace-abc-456"
  }
}
```

> To rotate `gateway_api_key` or `webhook_secret`, those are environment variables on the server — the frontend has no role in changing them.

### Response — `200 OK`

Same shape as the create response.

---

## 5. Delete Channel

### Request

```
DELETE /api/channels/{channel_id}
Authorization: Bearer <access_token>
```

### Response — `204 No Content`

> Deleting the channel does **not** disconnect the gateway session. The frontend should call the gateway's `DELETE /sessions/{tenantId}` endpoint separately if needed (requires direct gateway access).

---

## 6. Gateway Session Setup (Post-Creation Flow)

After creating the channel on the backend, the WhatsApp number needs to be linked by scanning a QR code. This is done directly against the Baileys gateway — the backend does not proxy these requests.

### Step 1 — Create gateway session

```
POST {gateway_url}/sessions
X-Gateway-Token: {gateway_api_key}
Content-Type: application/json
```

```json
{
  "tenantId": "workspace-abc-123",
  "webhookUrl": "https://api.chaai.online/webhooks/whatsapp-unofficial/workspace-abc-123",
  "webhookSecret": "<WHATSAPP_WEBHOOK_SECRET from server env>"
}
```

> The `webhookUrl` must be exactly `{backend_url}/webhooks/whatsapp-unofficial/{tenant_id}`. The `webhookSecret` value is the `WHATSAPP_WEBHOOK_SECRET` environment variable — the backend uses it to verify all inbound callbacks. Contact your backend admin for the value if you don't have access to server env vars.

**Response:**
```json
{ "status": "session created" }
```

---

### Step 2 — Show QR code to user

Poll or display the QR code for scanning:

**Option A — Embed QR image directly (simplest):**
```
GET {gateway_url}/sessions/{tenantId}/qr.png
```
Render as `<img src="{gateway_url}/sessions/{tenantId}/qr.png" />`. No auth header needed.

**Option B — Get QR string and render yourself:**
```
GET {gateway_url}/sessions/{tenantId}/qr
X-Gateway-Token: {gateway_api_key}
```
```json
{ "qr": "2@c582i1QHVTP..." }
```
Pass the string to any QR code library (e.g. `qrcode.react`).

**Option C — Open QR HTML page in new tab:**
```
{gateway_url}/sessions/{tenantId}/qr.html
```
No auth needed.

> QR codes expire after ~60 seconds and are regenerated automatically. Poll or refresh every 30 seconds until connected.

---

### Step 3 — Poll for connection status

```
GET {gateway_url}/sessions/{tenantId}
X-Gateway-Token: {gateway_api_key}
```

**When connecting (QR not yet scanned):**
```json
{ "status": null }
```

**When connected:**
```json
{
  "status": {
    "id": "919876543210:1@s.whatsapp.net",
    "name": "Business Name"
  }
}
```

Poll every 3–5 seconds. Once `status` is non-null, the number is linked and the channel is live.

---

## 7. Suggested UI Flow

```
Channel Settings → Add Channel → WhatsApp (Unofficial)
  │
  ├─ Form fields: tenant_id only (gateway config is server-side)
  │
  ├─ POST /api/channels/ → on success, get channel.id
  │
  ├─ POST {gateway_url}/sessions  (create session with webhook URL)
  │
  ├─ Show QR code screen
  │   └─ <img src="{gateway_url}/sessions/{tenantId}/qr.png" />
  │   └─ Poll GET {gateway_url}/sessions/{tenantId} every 3s
  │
  └─ When status != null → show "Connected ✓" and phone number
```

---

## 8. Disconnecting / Re-linking

To disconnect a session (requires re-scan to reconnect):

```
DELETE {gateway_url}/sessions/{tenantId}
X-Gateway-Token: {gateway_api_key}
```

```json
{ "status": "session destroyed" }
```

After this the QR code flow must be repeated from Step 1.

---

## 9. Check Session Status (Dashboard badge)

To show a "Connected / Disconnected" badge on the channels list, call:

```
GET {gateway_url}/sessions/{tenantId}
X-Gateway-Token: {gateway_api_key}
```

| `status` value | Display |
|---|---|
| `null` | Disconnected / QR pending |
| `{ id, name }` | Connected — show phone number |
| `404 { "error": "session not found" }` | Session never created — show "Setup required" |

---

## 10. Error Handling Reference

| HTTP code | Source | Meaning |
|---|---|---|
| `201` | Backend | Channel created successfully |
| `400` | Backend | Missing credential field or gateway unreachable |
| `401` | Backend | Invalid or missing `Authorization` header |
| `402` | Backend | Workspace channel limit exceeded |
| `409` | Backend | `whatsapp_unofficial` channel already exists for this workspace |
| `404` | Gateway | Session not found on gateway |
| `200 { "error": "qr not ready" }` | Gateway | QR not generated yet — retry |
| `501` | Gateway | Media send not implemented yet |

---

## 11. What the Frontend Does NOT Need to Handle

- Webhook reception — webhooks go directly from the gateway to the backend. The frontend is not involved.
- Message sending — handled by the backend pipeline after the webhook is received. The frontend only reads conversations via the existing conversations API.
- Delivery status — not yet available for unofficial WhatsApp (gateway does not send delivery receipts back to the backend).
