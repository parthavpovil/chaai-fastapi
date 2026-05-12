# Unofficial WhatsApp Integration (Baileys Gateway)

**Branch:** main  
**Date:** 2026-05-12  
**Scope:** Add `whatsapp_unofficial` as a new channel type backed by a self-hosted Baileys (whatsapp-web.js) gateway, without touching the existing Meta Cloud API (`whatsapp`) channel.

---

## Background

The existing WhatsApp integration (`type="whatsapp"`) uses the official Meta Cloud API and requires a Meta Business Account, approved phone number, and webhook subscription with Meta. For use cases where a plain WhatsApp number (personal or business, no Meta approval needed) is sufficient, a self-hosted [Baileys](https://github.com/WhiskeySockets/Baileys) gateway can be used instead.

The Baileys gateway runs as a separate Node.js/Fastify service. It manages WhatsApp Web sessions via QR code scan and exposes a simple REST API for sending messages and receiving inbound messages via webhook callbacks.

This change adds first-class support for that gateway as `channel_type = "whatsapp_unofficial"` — a completely independent integration that shares the same conversation pipeline, RAG engine, flow engine, and escalation logic as all other channels.

---

## Architecture Overview

```
WhatsApp User
     │
     ▼
Baileys Gateway (Node.js, port 3000)
  - Manages WA Web session
  - Receives inbound messages
     │  POST /webhooks/whatsapp-unofficial/{tenantId}
     │  Header: X-Webhook-Secret
     │  Body: {"event":"message","data":{...}}
     ▼
Backend (FastAPI)
  - Verifies secret
  - Extracts message_data
  - Runs pipeline in background (RAG / Flow / Escalation)
     │  POST {gateway_url}/messages/send
     │  Header: X-Gateway-Token
     │  Body: {tenantId, jid, text}
     ▼
Baileys Gateway
     │
     ▼
WhatsApp User (reply delivered)
```

---

## What Changed

### No DB migration required

`Channel.type` is a plain `String` column. Adding `"whatsapp_unofficial"` as a type value requires no schema change. The `config` JSONB column is already flexible and stores any key-value pairs. The `UniqueConstraint("workspace_id", "type")` has no conflict since `"whatsapp_unofficial"` is a different string from `"whatsapp"`.

### Required environment variables (server-level)

```env
WHATSAPP_GATEWAY_URL=https://whatsapp.chaai.online
WHATSAPP_GATEWAY_API_KEY=c0780976304dda0bc8d4225d84ded9f9d6d46cd620dd606fb77056ddcfbf4ea6
WHATSAPP_WEBHOOK_SECRET=b75ae63318b8a79e6c54b1af9ffa7093ac5a79bcb35854857612d4b91a4874c3
```

These are global — shared across all `whatsapp_unofficial` channels on the platform. Only `tenant_id` is stored per-channel in the database.

---

### 1. New File — `app/services/whatsapp_unofficial_sender.py`

Sends outbound replies from the backend to the customer via the Baileys gateway.

**Function:**
```python
async def send_whatsapp_unofficial_message(
    gateway_url: str,   # e.g. "http://localhost:3000"
    api_key: str,       # X-Gateway-Token value
    tenant_id: str,     # tenantId registered on gateway
    recipient_phone: str,  # plain phone number, no JID suffix
    text: str,
) -> bool
```

**What it does:**
- Appends `@s.whatsapp.net` to `recipient_phone` to form the JID
- POSTs to `{gateway_url}/messages/send` with `X-Gateway-Token` header
- Returns `True` on success, `False` on any error (logs details)

**Mirrors pattern of:** [`app/services/telegram_sender.py`](../app/services/telegram_sender.py)

---

### 2. `app/services/channel_validator.py`

#### New method — `validate_unofficial_whatsapp(credentials)`

Validates the credentials provided when creating a `whatsapp_unofficial` channel:

| Field | Required | Description |
|---|---|---|
| `tenant_id` | ✓ | Unique ID for the gateway session |
| `gateway_url` | ✓ | Base URL of the Baileys gateway |
| `gateway_api_key` | ✓ | API key for the gateway (`X-Gateway-Token`) |
| `webhook_secret` | ✓ | Secret the gateway sends in `X-Webhook-Secret` |

Also performs a live reachability check by calling `GET {gateway_url}/health`. Raises `ChannelValidationError` if the gateway is unreachable.

Returns:
```python
{"valid": True, "tenant_id": "...", "gateway_url": "...", "platform": "whatsapp_unofficial"}
```

#### Updated — `validate_channel_credentials()`

Added `elif channel_type == "whatsapp_unofficial":` branch before the final `else` that raises for unsupported types.

---

### 3. `app/routers/channels.py`

#### New schema — `UnofficialWhatsAppConfigRequest`

```python
class UnofficialWhatsAppConfigRequest(BaseModel):
    tenant_id: str       # Gateway session identifier
    gateway_url: str     # e.g. "http://localhost:3000"
    gateway_api_key: str # X-Gateway-Token value
    webhook_secret: str  # X-Webhook-Secret value
```

All four fields are stored in `Channel.config` as encrypted JSONB (same encryption as `bot_token` for Telegram). No special creation logic needed — the generic credential-encryption loop in `create_channel()` handles it automatically.

**To create a channel via API:**
```bash
curl -X POST https://your-backend/api/channels/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_type": "whatsapp_unofficial",
    "name": "WhatsApp (Unofficial)",
    "credentials": {
      "tenant_id": "workspace-abc",
      "gateway_url": "http://localhost:3000",
      "gateway_api_key": "dev-local",
      "webhook_secret": "your-secret"
    }
  }'
```

---

### 4. `app/services/webhook_handlers.py`

#### Updated — `_matches_channel_identifier()`

Added case for `whatsapp_unofficial` that decrypts and compares `config["tenant_id"]` against the `tenant_id` path parameter from the webhook URL:

```python
elif channel.type == "whatsapp_unofficial":
    encrypted_tenant_id = channel.config.get("tenant_id")
    if encrypted_tenant_id:
        return decrypt_credential(encrypted_tenant_id) == identifier
```

#### New method — `handle_whatsapp_unofficial_webhook(payload, headers, tenant_id)`

Full webhook handler for inbound gateway events:

1. Parses JSON body
2. Looks up channel via `get_channel_by_webhook_path("whatsapp_unofficial", tenant_id)`
3. Verifies `X-Webhook-Secret` header using `hmac.compare_digest` against stored (decrypted) `webhook_secret`
4. Routes by `event` field:
   - `"qr"` / `"connected"` / `"disconnected"` → returns `{"status": "ignored"}` (session lifecycle events, no processing needed)
   - `"message"` → extracts message data, returns success dict
   - anything else → ignored

#### New private method — `_extract_unofficial_whatsapp_message(webhook_data, tenant_id)`

Maps the Baileys webhook payload to the internal `message_data` dict used by the pipeline:

| Gateway field | Internal field | Transform |
|---|---|---|
| `data.senderId` | `external_contact_id` | Strip `@s.whatsapp.net` or `@g.us` |
| `data.messageId` | `external_message_id` | None |
| `data.text` | `content` | None |
| `data.type` | `msg_type` | None (`text`/`image`/`video`/`audio`/`document`) |
| `data.timestamp` | `message_metadata.timestamp` | Divide by 1000 (ms → s) |
| `data.chatId` | `message_metadata.chat_id` | None |
| `data.caption` | `content` | For media messages |
| `data.mimeType` | `media_mime_type` | For media messages |

#### Updated — `process_webhook()` convenience function

Added `elif channel_type == "whatsapp_unofficial":` routing branch.

---

### 5. `app/routers/webhooks.py`

#### New endpoint — `POST /webhooks/whatsapp-unofficial/{tenant_id}`

Receives inbound webhooks from the Baileys gateway. No signature middleware needed at the router level (verification happens inside the handler). Flow:

1. Calls `WebhookHandlers.handle_whatsapp_unofficial_webhook()`
2. Claims idempotency slot via `_claim_inbound_message("whatsapp_unofficial", external_msg_id)` (Redis, 24h TTL; DB unique constraint as second guard)
3. Decrypts channel credentials from `Channel.config` to build `unofficial_whatsapp_context`
4. Launches `_run_pipeline_with_own_session()` as a background task via `safe_create_task()`
5. Returns `{"status": "ok"}` immediately (does not wait for pipeline)

#### Updated — `_run_pipeline_with_own_session()` and `_run_message_pipeline()`

Both functions now accept `unofficial_whatsapp_context: dict = None`. The context dict carries:

```python
{
    "gateway_url": str,      # decrypted
    "api_key": str,          # decrypted
    "tenant_id": str,        # decrypted
    "recipient_phone": str,  # plain phone number from external_contact_id
}
```

#### Updated — Flow engine check

Extended from `if channel_type == "whatsapp":` to:
```python
if channel_type in ("whatsapp", "whatsapp_unofficial"):
```
This ensures the flow engine (multi-step conversation flows) applies to unofficial WhatsApp sessions as well.

#### Updated — 3 pipeline send points

`elif channel_type == "whatsapp_unofficial" and unofficial_whatsapp_context:` added at each of the three outbound send points:

| Send point | Trigger |
|---|---|
| Direct routing ack | AI disabled + human agents enabled |
| AI agent reply | `ai_mode = "ai_agent"` |
| RAG reply | Default RAG response |

All three call `send_whatsapp_unofficial_message()` from the new sender service.

---

## Gateway Configuration

When creating a WhatsApp session on the Baileys gateway, set `webhookUrl` to point to the backend:

```bash
curl -X POST http://localhost:3000/sessions \
  -H "Content-Type: application/json" \
  -H "X-Gateway-Token: dev-local" \
  -d '{
    "tenantId": "workspace-abc",
    "webhookUrl": "https://your-backend.com/webhooks/whatsapp-unofficial/workspace-abc",
    "webhookSecret": "your-secret"
  }'
```

The `tenantId` in this call must match the `tenant_id` stored in the backend channel config.

---

## End-to-End Test Flow

1. Start the Baileys gateway (`npm start` in the gateway directory)
2. Create a `whatsapp_unofficial` channel via `POST /api/channels/`
3. Create a gateway session and scan the QR code at `GET /sessions/{tenantId}/qr.html`
4. Send a WhatsApp message to the connected number
5. Gateway fires `POST /webhooks/whatsapp-unofficial/{tenantId}` to backend
6. Backend pipeline runs: message stored → RAG response generated → reply sent via `POST {gateway_url}/messages/send`
7. Verify: message and reply appear in the conversation dashboard

---

## Files Changed

| File | Type | Description |
|---|---|---|
| `app/services/whatsapp_unofficial_sender.py` | **New** | Outbound sender via Baileys gateway |
| `app/services/channel_validator.py` | Modified | Add `validate_unofficial_whatsapp()` + routing branch |
| `app/routers/channels.py` | Modified | Add `UnofficialWhatsAppConfigRequest` schema |
| `app/services/webhook_handlers.py` | Modified | Channel lookup, inbound handler, message extractor |
| `app/routers/webhooks.py` | Modified | New endpoint, pipeline wiring, flow engine, 3 send points |

---

## No Breaking Changes

- All existing `whatsapp` (Meta Cloud API) endpoints and handlers are untouched
- All existing `telegram` and `instagram` flows are untouched
- No DB migration required
- No new environment variables required (all config per-channel in JSONB)
