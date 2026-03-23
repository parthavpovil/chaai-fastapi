# WhatsApp Features — Developer Reference

Complete reference for all WhatsApp-specific APIs, webhooks, WebSocket events, and the processing pipeline.

---

## Table of Contents

**Inbound**
1. [Overview](#overview)
2. [Webhook Setup](#webhook-setup)
3. [Inbound Message Pipeline](#inbound-message-pipeline)
4. [Supported Message Types](#supported-message-types)
5. [Delivery & Read Receipts](#delivery--read-receipts)

**Automation & Outbound**

6. [Flow Builder](#flow-builder)
7. [WhatsApp Templates](#whatsapp-templates)
8. [Broadcasts](#broadcasts)

**Infrastructure**

9. [Media Storage (Cloudflare R2)](#media-storage-cloudflare-r2)
10. [WebSocket Events](#websocket-events)
11. [Environment Variables](#environment-variables)
12. [Docker Setup](#docker-setup)
13. [Database Migrations](#database-migrations)

---

## Overview

WhatsApp support is built on the **Meta WhatsApp Cloud API**. The backend receives inbound messages and delivery receipts via webhook, processes them through the pipeline, and sends outbound messages (replies, interactive flows, templates, broadcasts) back through the Graph API.

```
Customer's WhatsApp
       │
       ▼
Meta Cloud API
       │  POST /webhooks/whatsapp/{phone_number_id}
       ▼
chaai backend
       │
       ├── Text message     → Flow engine → RAG / Agent reply
       ├── Media message    → Download → R2 storage → store record
       ├── Location         → store record
       ├── Interactive      → Flow engine (button/list reply)
       ├── Reaction         → store record
       └── Status update    → update delivery_status → WebSocket push
```

---

## Webhook Setup

### Verification (GET)

Meta calls this once when you subscribe the webhook in the Meta Developer Console.

```
GET /webhooks/whatsapp/{phone_number_id}
```

| Parameter | Description |
|---|---|
| `hub.mode` | Always `subscribe` |
| `hub.verify_token` | Must match `META_VERIFY_TOKEN` in your `.env` |
| `hub.challenge` | Random string — echo it back to confirm |

**Response:** The challenge string as plain text (`200 OK`).

**To set up in Meta Developer Console:**
1. Go to App → WhatsApp → Configuration
2. Callback URL: `https://your-domain.com/webhooks/whatsapp/{phone_number_id}`
3. Verify Token: the value of `META_VERIFY_TOKEN` in your `.env`
4. Subscribe to: `messages` field

### Inbound Messages (POST)

```
POST /webhooks/whatsapp/{phone_number_id}
```

**Headers:** `X-Hub-Signature-256: sha256=<hmac>` — verified against `WHATSAPP_APP_SECRET`

**Always returns `200 {"status": "ok"}`** regardless of processing outcome. This is intentional — returning non-200 causes Meta to retry aggressively.

---

## Inbound Message Pipeline

Every inbound WhatsApp message goes through these steps in order:

```
1.  Signature verification (X-Hub-Signature-256)
2.  Parse webhook payload
3.  Check for delivery status updates → handle separately (see Delivery & Read Receipts)
4.  Extract message (type, content, media_id, location, etc.)
5.  Duplicate check (external_message_id)
6.  Tier limit check (monthly message quota)
7.  Get or create Contact
8.  Block check → if blocked, store + auto-reply + halt
9.  Business hours check → if outside hours, store + auto-reply + maybe halt
10. Get or create Conversation
11. If media message → download from WhatsApp → upload to R2 → get permanent URL
12. Store Message record with all fields
13. Notify dashboard via WebSocket (new_message event)
14. If non-text (media/location/reaction) → STOP (no AI)
15. Flow engine check → if conversation is mid-flow OR keyword triggers a flow → handle flow → STOP
16. Escalation classifier → if triggered → escalate → STOP
17. RAG engine → generate AI response → store + notify
```

**Key rule:** Only text messages reach the flow engine, escalation classifier, and RAG. Media, location, and reactions are stored and surfaced to agents but do not trigger AI responses.

---

## Supported Message Types

The `msg_type` field on the `Message` model stores the type.

### Text
```json
{
  "type": "text",
  "text": { "body": "Hello, I need help" }
}
```
Stored as: `msg_type="text"`, `content="Hello, I need help"`

### Image / Video / Audio / Document / Sticker
```json
{
  "type": "image",
  "image": {
    "id": "media-id-from-whatsapp",
    "mime_type": "image/jpeg",
    "caption": "optional caption"
  }
}
```
Stored as: `msg_type="image"`, `content="optional caption"`, `media_url="https://media.yourdomain.com/..."`, `media_mime_type="image/jpeg"`

The `media_id` from WhatsApp is **temporary** (~5 minutes). The pipeline immediately downloads it and uploads to R2 before storing the record.

**Size limits enforced by WhatsApp:**
| Type | Limit |
|---|---|
| Image | 5 MB |
| Video | 16 MB |
| Audio | 16 MB |
| Document | 100 MB |

### Location
```json
{
  "type": "location",
  "location": {
    "latitude": 12.9716,
    "longitude": 77.5946,
    "name": "Bangalore"
  }
}
```
Stored as: `msg_type="location"`, `location_lat=12.9716`, `location_lng=77.5946`, `location_name="Bangalore"`, `content="Bangalore"`

### Interactive (Button Reply / List Reply)

Sent when a customer taps a button or selects a list item from a flow step.

```json
{
  "type": "interactive",
  "interactive": {
    "type": "button_reply",
    "button_reply": {
      "id": "haircut",
      "title": "Haircut"
    }
  }
}
```
Stored as: `msg_type="interactive"`, `content="Haircut"`, `extra_data.interactive_id="haircut"`

The flow engine reads `extra_data.interactive_id` to advance the flow state.

### Reaction
```json
{
  "type": "reaction",
  "reaction": {
    "message_id": "wamid.xxx",
    "emoji": "👍"
  }
}
```
Stored as: `msg_type="reaction"`, `content="👍"`

---

## Delivery & Read Receipts

Meta sends status updates in the same webhook endpoint as messages, inside a `statuses` array instead of `messages`.

```
Customer reads message
       │
       ▼
Meta sends POST /webhooks/whatsapp/{phone_number_id}
{
  "entry": [{
    "changes": [{
      "value": {
        "statuses": [{
          "id": "wamid.HBgM...",
          "status": "read",
          "timestamp": "1711180800",
          "recipient_id": "919876543210"
        }]
      }
    }]
  }]
}
       │
       ▼
Backend looks up Message by whatsapp_message_id
       │
       ▼
Updates delivery_status + read_at / delivered_at / failed_reason
       │
       ▼
Pushes message_status_update via WebSocket to dashboard
```

### Status progression

```
sent → delivered → read
         └→ failed (at any point)
```

Status only moves **forward** — a `read` message can never revert to `delivered`. If the incoming status rank is lower than the current one, the update is silently ignored.

### Fields updated per status

| Status | Field set |
|---|---|
| `delivered` | `delivery_status="delivered"`, `delivered_at=<timestamp>` |
| `read` | `delivery_status="read"`, `read_at=<timestamp>` |
| `failed` | `delivery_status="failed"`, `failed_reason=<error title>` |

---

## Flow Builder

Flows let you automate multi-step WhatsApp conversations without AI. Common use cases: appointment booking, lead qualification, FAQ menus, order status checks.

### How flows work

```
Inbound message arrives
       │
       ├── Is conversation mid-flow?
       │     └── YES → advance_flow() → send next step → DONE (skip RAG)
       │
       └── Does message match a keyword trigger?
             └── YES → start_flow() → send first step → DONE (skip RAG)
                   NO → proceed to escalation / RAG
```

### Step types

| Type | What it sends | What it collects |
|---|---|---|
| `buttons` | WhatsApp interactive button message (max 3 buttons) | Button reply ID |
| `list` | WhatsApp list message (scrollable options) | Row selection ID |
| `free_text` | Plain text question | Any text reply, saved to `collected_data` |
| `condition` | Nothing — evaluates collected data, routes to different step | — |
| `handoff` | Nothing — marks flow abandoned, escalates conversation | — |
| `end` | Nothing — marks flow completed | — |

### Step schema

```json
{
  "id": "ask_service",
  "type": "buttons",
  "text": "What would you like to book?",
  "buttons": [
    { "id": "haircut", "title": "Haircut" },
    { "id": "massage", "title": "Massage" },
    { "id": "other",   "title": "Something else" }
  ],
  "transitions": {
    "haircut": "ask_time",
    "massage": "ask_time",
    "other":   "handoff"
  },
  "default_next": "ask_time"
}
```

For `free_text` steps:
```json
{
  "id": "ask_time",
  "type": "free_text",
  "text": "What date and time works for you?",
  "saves_as": "preferred_time",
  "next": "confirm"
}
```

### Collected data

As the customer moves through a flow, their answers are stored in `ConversationFlowState.collected_data`:
```json
{
  "service": "haircut",
  "preferred_time": "Tomorrow 3pm"
}
```
This is available for agents to view when the conversation is handed off.

### API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/flows` | Create flow |
| `GET` | `/api/flows` | List flows |
| `GET` | `/api/flows/{id}` | Get flow + steps |
| `PUT` | `/api/flows/{id}` | Update flow |
| `DELETE` | `/api/flows/{id}` | Delete flow |
| `POST` | `/api/flows/{id}/duplicate` | Clone flow (inactive copy) |
| `GET` | `/api/flows/{id}/stats` | Completion rate, started/completed/abandoned counts |

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md#flow-builder) for full request/response schemas.

---

## WhatsApp Templates

Templates are pre-approved message formats required by Meta for any **outbound** message to a customer who hasn't messaged you in the last 24 hours. Used for broadcasts and re-engagement.

### Lifecycle

```
Create (draft)
    │
    ▼ POST /api/templates/{id}/submit
Pending (submitted to Meta)
    │
    ├── Approved  ← background task syncs every hour
    └── Rejected  ← rejection_reason stored, can edit and resubmit
```

### Template variables

Use `{{1}}`, `{{2}}`, `{{3}}` (1-indexed) in the body. When sending via broadcast, variables are resolved per-contact using `variable_mapping`.

Example body: `"Hi {{1}}, your order #{{2}} is ready for pickup."`

### Requirements from Meta

- `name` must be lowercase with underscores only (e.g. `order_ready`)
- `category` must be `MARKETING`, `UTILITY`, or `AUTHENTICATION`
- Templates with promotional content must use `MARKETING` category
- Approval typically takes a few minutes to 24 hours

### Channel prerequisite

The WhatsApp channel must have `waba_id` stored in its encrypted config (alongside `phone_number_id` and `access_token`). This is the WhatsApp Business Account ID from Meta Business Manager.

### API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/templates` | Create template (draft) |
| `GET` | `/api/templates` | List templates |
| `GET` | `/api/templates/{id}` | Get template |
| `PUT` | `/api/templates/{id}` | Update (draft/rejected only) |
| `DELETE` | `/api/templates/{id}` | Delete |
| `POST` | `/api/templates/{id}/submit` | Submit to Meta for approval |
| `GET` | `/api/templates/{id}/preview` | Preview rendered structure |

---

## Broadcasts

Send an approved template to a filtered audience. Broadcasts are **queued via Redis** and executed by the arq worker process at ~80 messages/second (the WhatsApp Cloud API rate limit).

### How a broadcast send works

```
POST /api/broadcasts/{id}/send
       │
       ▼
enqueue_broadcast() → pushes job to Redis
       │
       ▼  (picked up by arq worker)
resolve_audience()  → query contacts WHERE opted_out=false AND phone IS NOT NULL
       │             + apply tag/manual filter
       ▼
For each contact:
  resolve_variables() → substitute {{1}} → contact.name, etc.
  send_single_template_message() → Graph API call
  store BroadcastRecipient record (status=sent, wamid stored)
  sleep 13ms  ← rate limit spacing
       │
       ▼
broadcast.status = "sent"
```

### Audience types

| `audience_type` | `audience_filter` | Who gets it |
|---|---|---|
| `all` | `null` | Every opted-in contact with a phone |
| `tag` | `{"tags": ["vip", "repeat"]}` | Contacts whose tags overlap the list |
| `manual` | `{"contact_ids": ["uuid1", "uuid2"]}` | Specific contacts |

### Opt-out handling

If a contact sends `STOP`, `UNSUBSCRIBE`, `OPT OUT`, or `REMOVE ME`, `contact.broadcast_opted_out` is set to `true` in the inbound webhook handler. `resolve_audience()` automatically excludes opted-out contacts.

### Broadcast statuses

| Status | Meaning |
|---|---|
| `draft` | Not yet sent, can still edit |
| `queued` | Enqueued for immediate sending |
| `scheduled` | Enqueued with a future `run_at` time |
| `sending` | Worker is currently sending |
| `sent` | All recipients processed |
| `cancelled` | Cancelled before completion |

### Delivery tracking

After the broadcast sends, Meta fires delivery/read status webhooks for each message. These are matched to `BroadcastRecipient` records via `whatsapp_message_id` and update `status`, `delivered_at`, `read_at`, or `failed_reason`.

### API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/broadcasts` | Create broadcast (draft) |
| `GET` | `/api/broadcasts` | List broadcasts |
| `GET` | `/api/broadcasts/{id}` | Get broadcast |
| `PUT` | `/api/broadcasts/{id}` | Update (draft only) |
| `POST` | `/api/broadcasts/{id}/send` | Enqueue for sending |
| `POST` | `/api/broadcasts/{id}/cancel` | Cancel |
| `GET` | `/api/broadcasts/{id}/stats` | Delivery/read rates |
| `GET` | `/api/broadcasts/{id}/recipients` | Per-contact delivery records (paginated) |

---

## Media Storage (Cloudflare R2)

WhatsApp media URLs expire in ~5 minutes. The pipeline downloads and re-stores media immediately on receipt.

### Flow

```
Inbound media message arrives
       │  (media_id from WhatsApp payload)
       ▼
GET https://graph.facebook.com/v17.0/{media_id}
  → returns temporary download URL + mime_type
       │
       ▼
GET {temporary_url}  (with Bearer token)
  → raw file bytes
       │
       ▼
PUT to R2: media/{workspace_id}/{uuid}.{ext}
       │
       ▼
Permanent URL: https://{R2_PUBLIC_DOMAIN}/media/{workspace_id}/{uuid}.{ext}
       │
       ▼
Stored in Message.media_url
```

### R2 bucket setup (one-time)

1. Create bucket `chaai-media` in Cloudflare dashboard
2. Enable public access OR set up a custom domain (set as `R2_PUBLIC_DOMAIN`)
3. Create R2 API token with Object Read & Write on this bucket
4. Fill in the R2 env vars (see [Environment Variables](#environment-variables))

### Agent-uploaded media

Agents can also send media from the dashboard. Those files go through `upload_agent_media()` in `r2_storage.py` — same bucket, same path structure, but the bytes come from the dashboard file picker instead of WhatsApp.

---

## WebSocket Events

All events are broadcast to the workspace room. Clients receive all events for their workspace.

| Event type | When fired |
|---|---|
| `new_message` | Any new inbound or outbound message |
| `escalation` | Conversation escalated to human |
| `agent_claim` | Agent claims a conversation |
| `conversation_status_change` | Status changes (active/escalated/agent/resolved) |
| `agent_status_change` | Agent goes online/offline |
| `message_status_update` | WhatsApp delivery/read receipt arrives |

### `message_status_update` payload

Use this to show tick indicators (✓ sent, ✓✓ delivered, ✓✓ read in blue).

```json
{
  "type": "message_status_update",
  "message_id": "uuid",
  "whatsapp_message_id": "wamid.HBgMNjE5ODc2NTQzMjEwFQIAERgSM...",
  "status": "read",
  "timestamp": "1711180800"
}
```

**Status values:** `sent` | `delivered` | `read` | `failed`

**Note:** `timestamp` is a Unix timestamp string (from Meta), not ISO 8601.

---

## Environment Variables

Add these to your `.env` file:

```env
# WhatsApp
WHATSAPP_APP_SECRET=          # App secret from Meta Developer Console (for HMAC verification)
META_VERIFY_TOKEN=            # Token you set in Meta webhook subscription

# Cloudflare R2 (media storage)
R2_ACCOUNT_ID=                # Cloudflare account ID
R2_ACCESS_KEY_ID=             # R2 API token key ID
R2_SECRET_ACCESS_KEY=         # R2 API token secret
R2_BUCKET_NAME=chaai-media    # R2 bucket name
R2_PUBLIC_DOMAIN=media.yourdomain.com   # Public domain pointing to bucket

# Redis (broadcast queue)
REDIS_URL=redis://localhost:6379/0
```

**WhatsApp channel config** (stored encrypted in `Channel.config` JSONB):
```json
{
  "phone_number_id": "<encrypted>",
  "access_token": "<encrypted>",
  "waba_id": "<encrypted>"
}
```
`waba_id` is the WhatsApp Business Account ID — required for template submission. Get it from Meta Business Manager → WhatsApp accounts.

---

## Docker Setup

Add these services to your `docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes

arq-worker:
  build: ./backend
  command: arq app.tasks.broadcast_tasks.WorkerSettings
  depends_on:
    - redis
    - db
  env_file: .env
  restart: unless-stopped

volumes:
  redis_data:
```

The `arq-worker` uses the same backend image with a different entrypoint. It has no HTTP port — it just reads jobs from Redis and executes them.

**If you are not using broadcasts**, you can skip both `redis` and `arq-worker`. Flows, rich media, and delivery receipts work without Redis.

---

## Database Migrations

Run in this order after deploying the new code:

```bash
cd backend
alembic revision --autogenerate -m "wave1_4_whatsapp_features"
alembic upgrade head
```

### Tables created / modified

| Change | Table | Details |
|---|---|---|
| Columns added | `messages` | `message_type`, `media_url`, `media_mime_type`, `media_filename`, `media_size`, `location_lat`, `location_lng`, `location_name`, `whatsapp_message_id`, `delivery_status`, `sent_at`, `delivered_at`, `read_at`, `failed_reason` |
| Column changed | `messages` | `content` made nullable (was NOT NULL) |
| Columns added | `contacts` | `broadcast_opted_out`, `opted_out_at` |
| Table created | `flows` | Flow definitions |
| Table created | `conversation_flow_states` | Per-conversation flow progress |
| Table created | `whatsapp_templates` | Template library |
| Table created | `broadcasts` | Broadcast campaigns |
| Table created | `broadcast_recipients` | Per-contact delivery records |

---

*Last updated: 2026-03-23*
