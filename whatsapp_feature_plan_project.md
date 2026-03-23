# WhatsApp Feature Plan — Project-Specific Implementation Guide
**ChatSaaS — Phase 2, mapped to our actual codebase**
Last updated: March 2026

---

## How to Read This Document

Every section is written against what we actually have. File paths, function names, model field names, and migration column names are exact. "What we have" means the code as it stands on branch `claude/youthful-montalcini`. "What to change" means the minimum diff to make the feature work.

---

## Current WhatsApp State (What Actually Works)

| Feature | Where it lives |
|---|---|
| Inbound text message receive | `app/services/webhook_handlers.py` → `_extract_whatsapp_message()` line 272 |
| Signature verification (X-Hub-Signature-256) | `app/services/webhook_handlers.py` → `handle_whatsapp_webhook()` line 210 |
| Channel lookup by phone_number_id | `app/services/webhook_handlers.py` → `_matches_channel_identifier()` line 76 |
| Contact auto-create from inbound | `app/services/message_processor.py` → `get_or_create_contact()` line 139 |
| AI reply pipeline | `app/routers/webhooks.py` → POST `/webhooks/whatsapp/{phone_number_id}` |
| Agent claim + reply | `app/routers/conversations.py` |
| Outbound webhook events | `app/services/outbound_webhook_service.py` |
| CSAT, canned responses | `app/models/csat_rating.py`, `app/routers/canned_responses.py` |

**What `_extract_whatsapp_message()` currently ignores** (line 304-305):
```python
if message_type != "text":
    continue  # Skip non-text messages for now
```
This one `continue` is the root cause of waves 1, 2, and 3 not working.

---

## Wave 1 — Rich Messaging

### 1.1 Message Model — New Columns

**File:** `app/models/message.py`

Current fields:
```python
id, conversation_id, role, content (Text, NOT NULL), channel_type,
external_message_id, extra_data (JSONB → 'metadata' column), created_at
```

Add these columns:

```python
# Message type: text | image | video | audio | document | location | contacts | sticker | reaction | interactive
msg_type = Column("message_type", String, nullable=True, default="text")

# Media fields (populated when msg_type is image/video/audio/document/sticker)
media_url       = Column(String, nullable=True)   # permanent URL after we store it
media_mime_type = Column(String, nullable=True)   # e.g. "image/jpeg", "application/pdf"
media_filename  = Column(String, nullable=True)   # original filename (docs only)
media_size      = Column(Integer, nullable=True)  # bytes

# Location fields (populated when msg_type is location)
location_lat    = Column(Float, nullable=True)
location_lng    = Column(Float, nullable=True)
location_name   = Column(String, nullable=True)

# Delivery tracking (populated for outbound messages)
whatsapp_msg_id = Column("whatsapp_message_id", String, nullable=True, index=True)
delivery_status = Column(String, nullable=True)   # sent | delivered | read | failed
sent_at         = Column(DateTime(timezone=True), nullable=True)
delivered_at    = Column(DateTime(timezone=True), nullable=True)
read_at         = Column(DateTime(timezone=True), nullable=True)
failed_reason   = Column(String, nullable=True)
```

**Important:** `content` is currently `nullable=False`. For media messages, content will be empty/null. Change to `nullable=True` in the model and the migration.

**Alembic migration to create:**
```
alembic revision --autogenerate -m "add_media_and_delivery_fields_to_messages"
```

---

### 1.2 File Storage — Cloudflare R2

Replace the local `FileStorageService` with a new R2-backed service. R2 is S3-compatible so we use `boto3` with a custom endpoint. The existing `FileStorageService` interface stays the same — only the storage backend changes.

**New dependency to add to `requirements.txt`:**
```
boto3>=1.34.0
```

**New file:** `app/services/r2_storage.py`

```python
import boto3
import uuid
import mimetypes
from botocore.config import Config
from app.config import settings

ALLOWED_MIME_TYPES = {
    # Existing (documents for RAG)
    'application/pdf',
    'text/plain',
    # WhatsApp media
    'image/jpeg', 'image/png', 'image/webp',
    'video/mp4',
    'audio/ogg', 'audio/mpeg', 'audio/aac', 'audio/amr',
    'application/pdf',  # document messages
}

MEDIA_SIZE_LIMITS = {
    'image':    5  * 1024 * 1024,   # 5MB (WhatsApp limit)
    'video':    16 * 1024 * 1024,   # 16MB
    'audio':    16 * 1024 * 1024,   # 16MB
    'document': 100 * 1024 * 1024,  # 100MB
}


def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def download_and_store_whatsapp_media(
    media_id: str,
    access_token: str,
    workspace_id: str,
) -> dict:
    """
    Download media from WhatsApp Graph API and store in R2.
    Must be called immediately — WhatsApp URLs expire in ~5 minutes.
    Returns: { url, mime_type, size_bytes, filename }
    """
    import httpx

    async with httpx.AsyncClient() as client:
        # Step 1: Resolve temporary URL
        meta = await client.get(
            f"https://graph.facebook.com/v17.0/{media_id}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        meta.raise_for_status()
        download_url = meta.json()["url"]
        mime_type = meta.json().get("mime_type", "application/octet-stream")

        # Step 2: Download bytes
        file_resp = await client.get(
            download_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        file_resp.raise_for_status()
        file_bytes = file_resp.content

    # Step 3: Upload to R2
    ext = mimetypes.guess_extension(mime_type) or ""
    key = f"media/{workspace_id}/{uuid.uuid4()}{ext}"

    client = _get_r2_client()
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=mime_type,
    )

    public_url = f"https://{settings.R2_PUBLIC_DOMAIN}/{key}"

    return {
        "url": public_url,
        "mime_type": mime_type,
        "size_bytes": len(file_bytes),
        "filename": key.split("/")[-1],
    }


async def upload_agent_media(
    file_bytes: bytes,
    mime_type: str,
    workspace_id: str,
    original_filename: str = "",
) -> dict:
    """
    Upload media sent by an agent (from dashboard file picker) to R2.
    Returns: { url, mime_type, size_bytes, filename }
    """
    ext = mimetypes.guess_extension(mime_type) or ""
    key = f"media/{workspace_id}/{uuid.uuid4()}{ext}"

    client = _get_r2_client()
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=mime_type,
    )

    return {
        "url": f"https://{settings.R2_PUBLIC_DOMAIN}/{key}",
        "mime_type": mime_type,
        "size_bytes": len(file_bytes),
        "filename": original_filename or key.split("/")[-1],
    }
```

**New env vars to add to `app/config.py` (and `.env`):**
```
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=chaai-media
R2_PUBLIC_DOMAIN=media.yourdomain.com   # R2 custom domain or public bucket URL
```

**R2 bucket setup (one-time):**
- Create bucket `chaai-media` in Cloudflare dashboard
- Enable public access OR set up a custom domain
- Create R2 API token with Object Read & Write on this bucket
- Optionally set lifecycle rule: delete objects older than 90 days (configurable per tier)

**Existing `FileStorageService` stays for knowledge base documents (PDF/TXT).** Only WhatsApp media goes through R2. The two services are parallel, not merged.

`httpx` and `boto3` — both available (`httpx` already in requirements, add `boto3`).

---

### 1.3 Webhook Handler — Handle All Message Types

**File:** `app/services/webhook_handlers.py`

Replace the body of `_extract_whatsapp_message()` starting at line 291. Currently it has `if message_type != "text": continue`. Replace with a full dispatcher:

```python
for message in messages:
    message_type = message.get("type")
    msg_id = message.get("id")
    from_number = message.get("from")

    if message_type == "text":
        content = message.get("text", {}).get("body", "")
        if not content.strip():
            continue
        return {
            "external_message_id": msg_id,
            "content": content,
            "msg_type": "text",
            "external_contact_id": from_number,
            ...  # existing contact fields
        }

    elif message_type in ("image", "video", "audio", "document", "sticker"):
        media_obj = message.get(message_type, {})
        return {
            "external_message_id": msg_id,
            "content": media_obj.get("caption", ""),  # caption optional
            "msg_type": message_type,
            "media_id": media_obj.get("id"),           # will be downloaded by processor
            "media_mime_type": media_obj.get("mime_type"),
            "media_filename": media_obj.get("filename"),  # docs only
            "external_contact_id": from_number,
            ...
        }

    elif message_type == "location":
        loc = message.get("location", {})
        return {
            "external_message_id": msg_id,
            "content": loc.get("name", "Location shared"),
            "msg_type": "location",
            "location_lat": loc.get("latitude"),
            "location_lng": loc.get("longitude"),
            "location_name": loc.get("name"),
            "external_contact_id": from_number,
            ...
        }

    elif message_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")  # button_reply | list_reply
        if interactive_type == "button_reply":
            btn = interactive.get("button_reply", {})
            return {
                "external_message_id": msg_id,
                "content": btn.get("title", ""),
                "msg_type": "interactive",
                "interactive_id": btn.get("id"),   # the button's id field
                "external_contact_id": from_number,
                ...
            }
        elif interactive_type == "list_reply":
            row = interactive.get("list_reply", {})
            return {
                "external_message_id": msg_id,
                "content": row.get("title", ""),
                "msg_type": "interactive",
                "interactive_id": row.get("id"),
                "external_contact_id": from_number,
                ...
            }

    elif message_type == "reaction":
        reaction = message.get("reaction", {})
        return {
            "external_message_id": msg_id,
            "content": reaction.get("emoji", ""),
            "msg_type": "reaction",
            "external_contact_id": from_number,
            ...
        }

    # statuses arrive separately — handled in Wave 2
```

Also add a new handler for the `statuses` array in the same webhook payload (Wave 2 — see below).

---

### 1.4 Message Processor — Download Media Before Storing

**File:** `app/services/message_processor.py`

`create_message()` currently takes only `content`, `role`, `channel_type`, `external_message_id`, `metadata`. Extend it with the new fields:

```python
async def create_message(
    self,
    conversation_id: str,
    content: str,
    role: str = "customer",
    channel_type: str = "webchat",
    external_message_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    # New optional media params
    msg_type: str = "text",
    media_url: Optional[str] = None,
    media_mime_type: Optional[str] = None,
    media_filename: Optional[str] = None,
    media_size: Optional[int] = None,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
    location_name: Optional[str] = None,
    whatsapp_msg_id: Optional[str] = None,
    delivery_status: Optional[str] = None,
) -> Message:
```

In `preprocess_message()`, if `message_data` contains a `media_id`, call `FileStorageService.download_and_store_whatsapp_media()` before calling `create_message()`. The `access_token` comes from the channel's decrypted config.

---

### 1.5 Outbound Media — New Endpoint

**New endpoint in:** `app/routers/conversations.py`

```
POST /api/conversations/{conversation_id}/messages/media
```

Request body:
```json
{
  "type": "image",
  "media_url": "https://yourcdn.com/uploaded/file.jpg",
  "caption": "optional caption"
}
```

This endpoint:
1. Validates the conversation belongs to the workspace
2. Calls the WhatsApp Graph API to send the media message
3. Stores the sent message with `role="agent"`, `msg_type=type`, `media_url`, `whatsapp_msg_id` from the API response, `delivery_status="sent"`
4. Fires `notify_new_message()` via WebSocket

The WhatsApp API call uses `channel.config` (decrypt `access_token` and `phone_number_id` via `app/services/encryption.py`).

---

### 1.6 Channel Config — Verify access_token is Stored

**File:** `app/routers/channels.py` (channel create/update flow)

Confirm the WhatsApp channel `config` JSONB stores:
- `phone_number_id` (encrypted) — already confirmed in `_matches_channel_identifier()` line 100
- `access_token` (encrypted) — needed for all Graph API calls
- `waba_id` (encrypted) — needed for Wave 4 template management. **Add this field to the channel connect form if not already collected.**

---

## Wave 2 — Delivery & Read Receipts

### 2.1 Handle `statuses` in the Webhook

**File:** `app/services/webhook_handlers.py`

The WhatsApp webhook POST body can contain either `messages` or `statuses` in `value`. Currently only `messages` is parsed. Add a second extractor:

```python
def _extract_whatsapp_statuses(
    self,
    webhook_data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Extract delivery status updates from WhatsApp webhook."""
    statuses = []
    for entry in webhook_data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for status in change.get("value", {}).get("statuses", []):
                statuses.append({
                    "whatsapp_msg_id": status.get("id"),   # wamid.xxx
                    "status": status.get("status"),         # sent|delivered|read|failed
                    "timestamp": status.get("timestamp"),
                    "recipient_id": status.get("recipient_id"),
                    "error": status.get("errors", [{}])[0].get("title") if status.get("errors") else None
                })
    return statuses
```

Call this alongside `_extract_whatsapp_message()` in `handle_whatsapp_webhook()`. If statuses are found, route to a new service function instead of the message pipeline.

---

### 2.2 Status Update Service

**New function in:** `app/services/message_processor.py`

```python
async def update_message_delivery_status(
    self,
    whatsapp_msg_id: str,
    status: str,            # sent | delivered | read | failed
    timestamp: str,
    workspace_id: str,
    error: Optional[str] = None
) -> Optional[Message]:
    """
    Find message by whatsapp_message_id and update delivery fields.
    Only updates forward (sent → delivered → read, never backwards).
    """
    STATUS_ORDER = {"sent": 1, "delivered": 2, "read": 3, "failed": 0}

    result = await self.db.execute(
        select(Message)
        .join(Conversation)
        .where(Message.whatsapp_msg_id == whatsapp_msg_id)
        .where(Conversation.workspace_id == workspace_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        return None

    current_order = STATUS_ORDER.get(message.delivery_status or "sent", 1)
    new_order = STATUS_ORDER.get(status, 0)
    if new_order <= current_order and status != "failed":
        return message  # don't go backwards

    ts = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    message.delivery_status = status
    if status == "delivered":
        message.delivered_at = ts
    elif status == "read":
        message.read_at = ts
    elif status == "failed":
        message.failed_reason = error

    await self.db.commit()
    return message
```

---

### 2.3 WebSocket — New Event Type

**File:** `app/services/websocket_events.py`

Add a new broadcast function alongside the existing ones (e.g. after `notify_new_message()` at line 420):

```python
async def notify_message_status_update(
    db: AsyncSession,
    workspace_id: str,
    message_id: str,
    whatsapp_msg_id: str,
    status: str,
    timestamp: str
) -> int:
    """Push delivery receipt update to dashboard in real time."""
    return await websocket_manager.broadcast_to_workspace(
        workspace_id,
        {
            "type": "message_status_update",
            "message_id": message_id,
            "whatsapp_message_id": whatsapp_msg_id,
            "status": status,               # sent | delivered | read | failed
            "timestamp": timestamp
        }
    )
```

Current WebSocket event types: `new_message`, `escalation`, `agent_claim`, `conversation_status_change`, `agent_status_change`, `document_processing`, `system_notification`, `workspace_stats_update`. This adds `message_status_update`.

---

### 2.4 Conversation Filter — "Read No Reply"

**File:** `app/routers/conversations.py`

Extend `GET /api/conversations` with two new `?status=` values:
- `?status=read_no_reply` — customer `read_at` is set on last outbound, no inbound since, >2 hours ago
- `?status=delivery_failed` — last outbound message has `delivery_status = "failed"`

These are SQL queries on the new `Message` columns joined against `Conversation`. No new model needed.

---

## Wave 3 — Interactive Messages + Flow Builder

### 3.1 Interactive Inbound — Already Handled Above

Wave 1's webhook extension already extracts `button_reply` and `list_reply` into `msg_type="interactive"` with `interactive_id`. The flow engine reads `interactive_id` to advance flow state.

### 3.2 New Models

**New file:** `app/models/flow.py`

```python
class Flow(Base):
    __tablename__ = "flows"

    id          = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name        = Column(String(100), nullable=False)
    trigger_keywords = Column(ARRAY(String), nullable=True)  # ["book", "appointment"]
    trigger_type     = Column(String(20), nullable=True)     # keyword | manual | ai_detected
    is_active   = Column(Boolean, default=True)
    steps       = Column(JSONB, nullable=False)               # full step tree
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="flows")
    flow_states = relationship("ConversationFlowState", back_populates="flow")


class ConversationFlowState(Base):
    __tablename__ = "conversation_flow_states"

    id              = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, unique=True)
    flow_id         = Column(PostgresUUID(as_uuid=True), ForeignKey("flows.id"), nullable=False)
    current_step_id = Column(String(50), nullable=False)
    collected_data  = Column(JSONB, default=dict)
    started_at      = Column(DateTime(timezone=True), server_default=func.now())
    completed_at    = Column(DateTime(timezone=True), nullable=True)
    abandoned_at    = Column(DateTime(timezone=True), nullable=True)

    flow         = relationship("Flow", back_populates="flow_states")
    conversation = relationship("Conversation")
```

Register in `app/models/__init__.py` and add `flows` / `flow_states` relationships to `Workspace` and `Conversation` models.

---

### 3.3 Flow Engine Service

**New file:** `app/services/flow_engine.py`

This is the core logic. It plugs into `preprocess_message()` / the webhook pipeline **before** the RAG call. The exact insertion point is in `app/routers/webhooks.py` inside the `POST /webhooks/whatsapp/{phone_number_id}` handler, after `process_incoming_message()` succeeds and before `rag_engine.generate_response()` is called.

```python
async def handle_message_with_flow_check(
    db: AsyncSession,
    conversation: Conversation,
    message: Message,
    workspace_id: str,
    channel: Channel
) -> bool:
    """
    Returns True if message was handled by a flow (caller should skip RAG).
    Returns False if no flow — caller proceeds to RAG.
    """
    # 1. Is conversation mid-flow?
    flow_state = await get_active_flow_state(db, str(conversation.id))
    if flow_state:
        await advance_flow(db, conversation, message, flow_state, channel)
        return True

    # 2. Does message trigger a flow by keyword?
    triggered = await find_keyword_trigger(db, workspace_id, message.content or "")
    if triggered:
        flow_state = await start_flow(db, str(conversation.id), triggered)
        await send_flow_step(db, conversation, flow_state, channel)
        return True

    return False  # proceed to RAG
```

Step types to implement: `buttons`, `list`, `free_text`, `condition`, `handoff`, `end`, `webhook`.

The `send_flow_step()` function calls the WhatsApp Graph API to send interactive messages (using the channel's decrypted `access_token` and `phone_number_id`).

---

### 3.4 Flow API Router

**New file:** `app/routers/flows.py` — register in `main.py`

```
POST   /api/flows                    Create flow
GET    /api/flows                    List flows (workspace-scoped)
GET    /api/flows/{id}               Get flow with steps
PUT    /api/flows/{id}               Update flow
DELETE /api/flows/{id}               Delete flow
POST   /api/flows/{id}/duplicate     Clone flow (copy steps JSONB)
POST   /api/flows/{id}/test          Send to a test phone number
POST   /api/flows/{id}/trigger       Manually trigger for a contact_id
GET    /api/flows/{id}/stats         Completion rate, step dropoff
```

Stats endpoint queries `ConversationFlowState` grouped by flow_id and step transition — no new table needed.

---

## Wave 4 — Template Manager + Broadcast

### 4.1 Prerequisite — WABA ID

**File:** `app/routers/channels.py` (WhatsApp channel connect flow)

Before anything in Wave 4 works, `waba_id` must be stored in `Channel.config`. Confirm the channel connect form collects it. If not, add it. The encrypted value goes alongside `phone_number_id` and `access_token` in the JSONB config.

---

### 4.2 New Models

**New file:** `app/models/whatsapp_template.py`

```python
class WhatsAppTemplate(Base):
    __tablename__ = "whatsapp_templates"

    id               = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id     = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name             = Column(String(100), nullable=False)  # lowercase_underscore only
    category         = Column(String(20), nullable=False)   # MARKETING | UTILITY | AUTHENTICATION
    language         = Column(String(10), nullable=False)   # "en" | "hi" | "ml" | "ta"
    status           = Column(String(20), default="draft")  # draft|pending|approved|rejected
    rejection_reason = Column(Text, nullable=True)
    header_type      = Column(String(20), nullable=True)    # none|text|image|video|document
    header_content   = Column(Text, nullable=True)
    body             = Column(Text, nullable=False)          # "Hi {{1}}, your order {{2}}..."
    footer           = Column(Text, nullable=True)
    buttons          = Column(JSONB, nullable=True)
    meta_template_id = Column(String(100), nullable=True)   # ID returned by Meta after submission
    submitted_at     = Column(DateTime(timezone=True), nullable=True)
    approved_at      = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
```

**New file:** `app/models/broadcast.py`

```python
class Broadcast(Base):
    __tablename__ = "broadcasts"

    id               = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id     = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name             = Column(String(100), nullable=False)
    template_id      = Column(PostgresUUID(as_uuid=True), ForeignKey("whatsapp_templates.id"), nullable=False)
    variable_mapping = Column(JSONB, nullable=True)    # {"{{1}}": "contact.name", "{{2}}": "static:40% off"}
    audience_type    = Column(String(20), nullable=False)   # all | tag | manual
    audience_filter  = Column(JSONB, nullable=True)    # {"tags": ["vip"]}
    recipient_count  = Column(Integer, nullable=True)
    status           = Column(String(20), default="draft")  # draft|scheduled|sending|sent|cancelled
    scheduled_at     = Column(DateTime(timezone=True), nullable=True)
    started_at       = Column(DateTime(timezone=True), nullable=True)
    completed_at     = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    recipients = relationship("BroadcastRecipient", back_populates="broadcast")


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"

    id                  = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    broadcast_id        = Column(PostgresUUID(as_uuid=True), ForeignKey("broadcasts.id"), nullable=False)
    contact_id          = Column(PostgresUUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    phone               = Column(String(20), nullable=False)   # E.164 format
    variable_values     = Column(JSONB, nullable=True)         # resolved per-contact variables
    status              = Column(String(20), default="pending") # pending|sent|delivered|read|failed
    whatsapp_message_id = Column(String(100), nullable=True)
    sent_at             = Column(DateTime(timezone=True), nullable=True)
    delivered_at        = Column(DateTime(timezone=True), nullable=True)
    read_at             = Column(DateTime(timezone=True), nullable=True)
    failed_reason       = Column(Text, nullable=True)

    broadcast = relationship("Broadcast", back_populates="recipients")
```

Audience resolution uses `Contact.tags` (already `ARRAY(String)`) — no schema change on Contact for audience filtering.

---

### 4.3 Contact Model — Add Opt-Out

**File:** `app/models/contact.py`

Add two columns:
```python
broadcast_opted_out = Column(Boolean, default=False, nullable=False)
opted_out_at        = Column(DateTime(timezone=True), nullable=True)
```

Opt-out detection goes in the WhatsApp webhook handler — before calling `process_incoming_message()`, check if the message content is in `["STOP", "UNSUBSCRIBE", "OPT OUT", "REMOVE ME"]`.

---

### 4.4 Broadcast Sending — Redis + arq Queue

We use Redis (Docker container) as the queue broker and `arq` as the async task worker. `arq` is fully asyncio-native — it fits the codebase without any sync/async bridging that Celery would require.

**New dependencies to add to `requirements.txt`:**
```
arq>=0.26.0
redis>=5.0.0
```

**Redis container setup** — add to `docker-compose.yml`:
```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes

volumes:
  redis_data:
```

**New env var in `app/config.py`:**
```
REDIS_URL=redis://localhost:6379/0
```

---

**New file:** `app/tasks/broadcast_tasks.py`

```python
import asyncio
from arq import create_pool
from arq.connections import RedisSettings
from app.config import settings


async def send_broadcast_job(ctx, broadcast_id: str, workspace_id: str):
    """
    arq worker job — sends one broadcast.
    Runs in the arq worker process, has its own DB session.
    """
    from app.database import AsyncSessionLocal
    from app.services.broadcast_service import execute_broadcast

    async with AsyncSessionLocal() as db:
        await execute_broadcast(db, broadcast_id, workspace_id)


class WorkerSettings:
    """arq worker configuration"""
    functions = [send_broadcast_job]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10       # max concurrent broadcasts
    job_timeout = 3600  # 1 hour max per broadcast


async def enqueue_broadcast(broadcast_id: str, workspace_id: str, run_at=None):
    """Enqueue a broadcast job. run_at is a datetime for scheduled sends."""
    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    await pool.enqueue_job(
        "send_broadcast_job",
        broadcast_id=broadcast_id,
        workspace_id=workspace_id,
        _defer_until=run_at,   # None = run immediately
    )
    await pool.aclose()
```

**New file:** `app/services/broadcast_service.py`

```python
async def execute_broadcast(db, broadcast_id: str, workspace_id: str):
    broadcast = await get_broadcast(db, broadcast_id, workspace_id)
    contacts = await resolve_audience(db, broadcast)

    broadcast.status = "sending"
    broadcast.started_at = datetime.now(timezone.utc)
    broadcast.recipient_count = len(contacts)
    await db.commit()

    for contact in contacts:
        try:
            resolved_vars = resolve_variables(broadcast.variable_mapping, contact)
            wamid = await send_single_template_message(db, broadcast, contact, resolved_vars)

            recipient = BroadcastRecipient(
                broadcast_id=broadcast_id,
                contact_id=str(contact.id),
                phone=contact.phone,
                variable_values=resolved_vars,
                status="sent",
                whatsapp_message_id=wamid,
                sent_at=datetime.now(timezone.utc),
            )
            db.add(recipient)
        except Exception as e:
            db.add(BroadcastRecipient(
                broadcast_id=broadcast_id,
                contact_id=str(contact.id),
                phone=contact.phone,
                status="failed",
                failed_reason=str(e),
            ))

        await db.commit()
        await asyncio.sleep(0.013)   # ~80 msg/sec — WhatsApp Cloud API rate limit

    broadcast.status = "sent"
    broadcast.completed_at = datetime.now(timezone.utc)
    await db.commit()


async def resolve_audience(db, broadcast) -> list:
    """Filter contacts by audience_type. Excludes opted-out contacts."""
    query = (
        select(Contact)
        .where(Contact.workspace_id == broadcast.workspace_id)
        .where(Contact.broadcast_opted_out == False)
        .where(Contact.phone.isnot(None))
    )
    if broadcast.audience_type == "tag":
        tags = broadcast.audience_filter.get("tags", [])
        query = query.where(Contact.tags.overlap(tags))   # PostgreSQL ARRAY && operator

    result = await db.execute(query)
    return result.scalars().all()
```

**In `app/routers/broadcasts.py`:**
```python
@router.post("/{broadcast_id}/send")
async def send_broadcast(broadcast_id: str, ...):
    broadcast = ...
    if broadcast.scheduled_at:
        await enqueue_broadcast(broadcast_id, workspace_id, run_at=broadcast.scheduled_at)
    else:
        await enqueue_broadcast(broadcast_id, workspace_id)
    broadcast.status = "scheduled" if broadcast.scheduled_at else "queued"
    await db.commit()
    return {"status": broadcast.status}
```

**Run the arq worker** (separate process alongside uvicorn):
```bash
arq app.tasks.broadcast_tasks.WorkerSettings
```

Add this as a separate service in `docker-compose.yml`.

**Tier gating** on recipient count uses the existing `TierManager` in `app/services/tier_manager.py`. Check limit before enqueuing: Free = block, Starter = 500, Growth = 5000, Pro = unlimited.

---

### 4.5 Template Submission to Meta

**New file:** `app/services/template_service.py`

Uses `httpx` (already available) to call:
```
POST https://graph.facebook.com/v17.0/{waba_id}/message_templates
Authorization: Bearer {access_token}
```

Status sync runs on a background task started in `main.py` lifespan (similar to how `agent_status_tasks.py` is registered). No cron library needed — use `asyncio.sleep(3600)` in a looping task.

---

### 4.6 API Routers — Two New Files

**New file:** `app/routers/templates.py`
```
POST   /api/templates
GET    /api/templates
GET    /api/templates/{id}
PUT    /api/templates/{id}
DELETE /api/templates/{id}
POST   /api/templates/{id}/submit
GET    /api/templates/{id}/preview
```

**New file:** `app/routers/broadcasts.py`
```
POST   /api/broadcasts
GET    /api/broadcasts
GET    /api/broadcasts/{id}
PUT    /api/broadcasts/{id}
POST   /api/broadcasts/{id}/send
POST   /api/broadcasts/{id}/cancel
GET    /api/broadcasts/{id}/stats
GET    /api/broadcasts/{id}/recipients
```

Register both in `main.py` alongside the existing 18 routers.

---

## Wave 5 — Commerce (Payment Links)

### 5.1 Use Stripe, Not Razorpay

`stripe` is already in `requirements.txt`. `app/services/stripe_service.py` already exists. We don't add Razorpay — Stripe Payment Links work everywhere.

### 5.2 New Model

**New file:** `app/models/payment.py`

```python
class Payment(Base):
    __tablename__ = "payments"

    id               = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id     = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    conversation_id  = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    contact_id       = Column(PostgresUUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    amount           = Column(Numeric(10, 2), nullable=False)
    currency         = Column(String(3), default="INR")
    description      = Column(Text, nullable=True)
    status           = Column(String(20), default="pending")  # pending|paid|expired|cancelled
    stripe_link_id   = Column(String(100), nullable=True)     # Stripe Payment Link ID
    payment_link_url = Column(String(500), nullable=True)
    paid_at          = Column(DateTime(timezone=True), nullable=True)
    expires_at       = Column(DateTime(timezone=True), nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
```

### 5.3 New Endpoints

**Add to:** `app/routers/conversations.py` (or a new `app/routers/payments.py`)

```
POST /api/conversations/{conversation_id}/payment-link
     Body: { amount, currency, description }
     → Creates Stripe Payment Link, sends WhatsApp message, stores Payment record

GET  /api/conversations/{conversation_id}/payments
     → Lists all payment records for this conversation
```

### 5.4 Stripe Webhook Extension

**File:** `app/routers/webhooks.py`

The Stripe webhook handler already exists at `POST /webhooks/stripe` (handles subscription events). Extend it to also handle `payment_link.completed` or `checkout.session.completed` events — look up the `Payment` record by Stripe link ID, mark as `paid`, send a WhatsApp confirmation message to the customer.

---

## Database Migration Order

Run Alembic migrations in this order — each wave must be migrated before the next wave's code is deployed:

| Order | Migration | Affects |
|---|---|---|
| 1 | Add columns to `messages` table | `msg_type`, `media_url`, `media_mime_type`, `media_filename`, `media_size`, `location_lat`, `location_lng`, `location_name`, `whatsapp_message_id`, `delivery_status`, `sent_at`, `delivered_at`, `read_at`, `failed_reason` |
| 2 | Make `messages.content` nullable | Content is null for pure media messages |
| 3 | Add columns to `contacts` table | `broadcast_opted_out`, `opted_out_at` |
| 4 | Create `flows` table | |
| 5 | Create `conversation_flow_states` table | |
| 6 | Create `whatsapp_templates` table | |
| 7 | Create `broadcasts` table | |
| 8 | Create `broadcast_recipients` table | |
| 9 | Create `payments` table | |

---

## New Dependencies Summary

Add to `requirements.txt`:
```
# Cloudflare R2 (S3-compatible object storage)
boto3>=1.34.0

# Redis queue for broadcasts
arq>=0.26.0
redis>=5.0.0
```

New env vars to add to `app/config.py` and `.env`:
```
# Cloudflare R2
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=chaai-media
R2_PUBLIC_DOMAIN=media.yourdomain.com

# Redis
REDIS_URL=redis://localhost:6379/0
```

New Docker services (add to `docker-compose.yml`):
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
```

---

## Existing Code That Does NOT Need Changing

These are already correct and handle the new features automatically:

| Component | Why it doesn't change |
|---|---|
| `app/services/encryption.py` | Decrypting `access_token` from channel config works as-is |
| `app/services/tier_manager.py` | Already has tier-based limit checking — add broadcast limits as new keys |
| `app/services/outbound_webhook_service.py` | Existing `trigger_event()` can fire new event types (`message.delivered`, `broadcast.sent`) with no code changes |
| `app/services/websocket_manager.py` | `broadcast_to_workspace()` is generic — new event types just need new callers |
| `app/services/escalation_classifier.py` | Flow's `handoff` step calls the existing escalation path |
| `app/services/rag_engine.py` | Flow engine returns `True` to skip RAG — no change to RAG itself |
| `app/services/auth_service.py` | All new routers use the same JWT auth dependency |
| `app/models/workspace.py` | Tier field already exists for broadcast gating |

---

## What is NOT Being Built

| Feature | Reason |
|---|---|
| Product catalog / WhatsApp Commerce | Requires Meta Commerce Manager setup — too much external dependency for v1 |
| Drag-and-drop flow builder UI | Not in backend scope |
| Razorpay | Stripe already integrated — use Stripe Payment Links instead |
| Typing indicator | Not needed |

---

## Timeline

| Week | What ships | Key files changed |
|---|---|---|
| 1 | Inbound media (images, docs, audio, location) parsed and stored | `webhook_handlers.py`, `message.py`, `file_storage.py` + migration |
| 2 | Outbound media from agents + `content` nullable + receipt field storage | `conversations.py` new endpoint + migration |
| 2–3 | Delivery/read receipts + `message_status_update` WebSocket event | `webhook_handlers.py`, `message_processor.py`, `websocket_events.py` |
| 3–4 | Interactive button/list messages + flow model | `flow.py` models + migration |
| 4–5 | Flow runtime engine + keyword triggers | `flow_engine.py`, `flows.py` router |
| 5 | Flow stats endpoint | `flows.py` router, query on `conversation_flow_states` |
| 6 | Template manager (create, submit to Meta, sync status) | `whatsapp_template.py`, `templates.py`, `template_service.py` |
| 7 | Broadcast campaigns (create, send, cancel) + opt-out handling | `broadcast.py`, `broadcasts.py`, `broadcast_service.py` |
| 8 | Broadcast analytics + recipient status tracking | `broadcasts.py` stats endpoint; receipt webhook updates `broadcast_recipients` |
| 9 | Stripe payment links in chat | `payment.py`, `payments.py` or extend `conversations.py`, extend `webhooks.py` Stripe handler |
| 10 | Polish, edge cases, load test, documentation | |
