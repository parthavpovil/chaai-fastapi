# Telegram: Complete Message Flow Documentation

This document describes everything that happens when a Telegram user sends a message to the bot — every branch, every feature flag, every scenario. It also explicitly notes where Telegram diverges from the WebChat widget flow.

For the WebChat flow, see [chat-widget-message-flow.md](chat-widget-message-flow.md).

---

## Table of Contents

1. [How Telegram Differs from WebChat — TL;DR](#how-telegram-differs-from-webchat--tldr)
2. [Architecture Overview](#architecture-overview)
3. [Key Files & Services](#key-files--services)
4. [Phase 0 — Channel Registration (One-Time Setup)](#phase-0--channel-registration-one-time-setup)
5. [Phase 1 — Incoming Webhook (Entry Point)](#phase-1--incoming-webhook-entry-point)
6. [Phase 2 — Message Extraction](#phase-2--message-extraction)
7. [Phase 3 — Message Processing Pipeline (Mostly Shared)](#phase-3--message-processing-pipeline-mostly-shared)
8. [Phase 4 — Routing Decision (Fully Shared)](#phase-4--routing-decision-fully-shared)
9. [Scenario A — No AI, No Agents (Silent Reception)](#scenario-a--no-ai-no-agents-silent-reception)
10. [Scenario B — No AI, Agents Enabled (Direct Routing)](#scenario-b--no-ai-agents-enabled-direct-routing)
11. [Scenario C — AI Agent Mode](#scenario-c--ai-agent-mode)
12. [Scenario D — RAG Mode (Default AI)](#scenario-d--rag-mode-default-ai)
13. [How Replies Are Delivered (Telegram Bot API)](#how-replies-are-delivered-telegram-bot-api)
14. [Agent/Owner Sending a Message](#agentowner-sending-a-message)
15. [Business Hours, Maintenance Mode, Blocking](#business-hours-maintenance-mode-blocking)
16. [Supported & Unsupported Message Types](#supported--unsupported-message-types)
17. [Delivery Status Tracking](#delivery-status-tracking)
18. [Webhook Retry Behaviour](#webhook-retry-behaviour)
19. [Edited Messages](#edited-messages)
20. [Deduplication](#deduplication)
21. [Contact & Conversation Identity](#contact--conversation-identity)
22. [Credential Storage & Security](#credential-storage--security)
23. [Complete Decision Tree](#complete-decision-tree)
24. [Database State Changes Per Scenario](#database-state-changes-per-scenario)
25. [Shared vs Unique — Full Comparison Table](#shared-vs-unique--full-comparison-table)

---

## How Telegram Differs from WebChat — TL;DR

| Concern | WebChat | Telegram |
|---------|---------|----------|
| Entry point | `POST /api/webchat/send` (customer calls us) | `POST /webhooks/telegram/{bot_token}` (Telegram calls us) |
| Auth / verification | Session token in request body | `X-Telegram-Bot-Api-Secret-Token` header (optional) |
| Reply delivery | WebSocket push to browser | HTTP POST to Telegram Bot API |
| Contact identity | `session_token` (ephemeral) | Telegram `user_id` (permanent) |
| Deduplication key | `external_message_id` (set by server) | `message_id` from Telegram payload |
| Media support | Text + file uploads | **Text only** (current implementation) |
| Delivery tracking | DB fields (`sent_at`, `delivered_at`, `read_at`) | None (fire-and-forget) |
| Edited messages | N/A | Not supported |
| Inline buttons / callbacks | N/A | Not supported |
| Core processing logic | `message_processor`, `rag_engine`, `escalation_router`, `ai_agent_runner` | **Same — fully shared** |

The routing logic, RAG pipeline, escalation classifier, AI agent runner, and token tracking are **identical** for Telegram and WebChat. The only differences are at the edges: how the message arrives and how the reply is sent back.

---

## Architecture Overview

```
Telegram User
    │
    └─ Sends message to bot in Telegram app
         │
         └─ Telegram Platform calls:
              POST /webhooks/telegram/{bot_token}
                   │
                   ├─ Signature verification (optional secret token)
                   ├─ Payload extraction
                   ├─ Channel lookup by bot_token
                   └─ _run_message_pipeline(channel_type="telegram", telegram_context=...)
                              │
                              ├─ (same pipeline as WebChat)
                              │
                              └─ On reply:
                                   send_telegram_message()
                                   POST https://api.telegram.org/bot{token}/sendMessage
                                        │
                                        └─ Telegram delivers to user
```

**Agent Dashboard** receives real-time WebSocket events (same as WebChat) — escalations, new messages, status changes. The dashboard is not affected by the delivery channel.

---

## Key Files & Services

| File | Purpose |
|------|---------|
| `app/routers/webhooks.py` | Telegram webhook HTTP endpoint + `_run_message_pipeline()` |
| `app/services/webhook_handlers.py` | Webhook signature verification + payload extraction |
| `app/services/telegram_sender.py` | Outbound message delivery via Telegram Bot API |
| `app/services/channel_validator.py` | Registers bot webhook at channel creation time |
| `app/services/webhook_security.py` | `verify_telegram_secret()` — timing-safe token comparison |
| `app/routers/conversations.py` | Agent-to-customer message sending (uses `telegram_sender`) |
| `app/models/channel.py` | Stores encrypted `bot_token` in `config` JSONB field |
| **Shared with WebChat** | |
| `app/services/message_processor.py` | Contact/conversation creation, deduplication, storage |
| `app/services/escalation_classifier.py` | Keyword + LLM escalation detection |
| `app/services/escalation_router.py` | Escalation orchestration + agent assignment |
| `app/services/rag_engine.py` | Full RAG pipeline |
| `app/services/ai_agent_runner.py` | AI agent execution + tool calling |
| `app/services/ai_agent_token_tracker.py` | Token logging + cost estimation |
| `app/services/websocket_events.py` | Agent dashboard WebSocket broadcasts |

---

## Phase 0 — Channel Registration (One-Time Setup)

Before any messages can be received, a Telegram channel must be created in the platform. This happens once per bot.

```
POST /api/channels  (body: {channel_type: "telegram", config: {bot_token: "7xxx:AAA..."}})
    │
    ├─ channel_validator.validate_telegram_credentials(bot_token)
    │      └─ GET https://api.telegram.org/bot{token}/getMe
    │         └─ FAIL (invalid token) → 400 error
    │
    ├─ Encrypt bot_token: encrypt_credential(bot_token)
    │      └─ Stored as Channel.config = {"bot_token": <ENCRYPTED>}
    │
    ├─ channel_validator.register_telegram_webhook(bot_token)
    │      └─ POST https://api.telegram.org/bot{token}/setWebhook
    │            body: {
    │              url: "https://{APP_URL}/webhooks/telegram/{bot_token}",
    │              secret_token: TELEGRAM_SECRET_TOKEN (from env, optional)
    │            }
    │
    └─ Channel row saved: {id, workspace_id, type="telegram", config={encrypted_token}}
```

From this point, Telegram will POST to `/webhooks/telegram/{bot_token}` for every message the bot receives.

---

## Phase 1 — Incoming Webhook (Entry Point)

**Endpoint:** `POST /webhooks/telegram/{bot_token}`
**Router:** `app/routers/webhooks.py` → `telegram_webhook()`

```
Telegram calls: POST /webhooks/telegram/{bot_token}
    │
    ├─ 1. Parse raw JSON body
    │
    ├─ 2. Signature Verification (if TELEGRAM_SECRET_TOKEN is configured)
    │      └─ Read header: X-Telegram-Bot-Api-Secret-Token
    │         └─ webhook_security.verify_telegram_secret(received_token)
    │            └─ secrets.compare_digest(received, expected)  ← timing-safe
    │               └─ MISMATCH → 403 (silently swallowed, returns {"ok": True})
    │
    ├─ 3. Route to handler
    │      └─ WebhookHandlers.handle_telegram_webhook(webhook_data, bot_token)
    │
    └─ 4. ALWAYS return HTTP 200 {"ok": True}
           (prevents Telegram retry even on error — see Webhook Retry section)
```

**Important:** The response is always `{"ok": True}` with HTTP 200. If processing fails, the error is logged but Telegram is never told about it (which would trigger retries for up to 24 hours).

---

## Phase 2 — Message Extraction

**Function:** `WebhookHandlers._extract_telegram_message()` in `app/services/webhook_handlers.py`

```
Incoming Telegram payload:
{
  "update_id": 12345,
  "message": {
    "message_id": 42,
    "from": {
      "id": 987654321,
      "first_name": "John",
      "last_name": "Doe",
      "username": "johndoe",
      "language_code": "en"
    },
    "chat": {
      "id": 987654321,
      "type": "private"
    },
    "date": 1715000000,
    "text": "Hello, I need help with my order"
  }
}

Extraction:
    │
    ├─ Check: does "message" key exist in payload?
    │      └─ No "message" → return None (ignore update — e.g. channel post, poll, etc.)
    │
    ├─ Check: does message have "text"?
    │      └─ No text OR text.strip() == "" → return None (ignore media, stickers, etc.)
    │
    └─ Extract fields:
           external_message_id  = str(message["message_id"])    → "42"
           content              = message["text"]               → "Hello, I need help..."
           external_contact_id  = str(from_user["id"])         → "987654321"
           contact_name         = "John Doe"
           contact_data         = {
               "username": "johndoe", 
               "language_code": "en",
               "chat_type": "private"
           }
           message_metadata     = {
               "date": 1715000000,
               "chat_id": 987654321,
               "platform": "telegram"
           }
```

**What gets ignored / returns None:**
- No `message` key (channel posts, poll updates, callback queries, inline queries)
- Empty or whitespace-only text
- Messages with only media (photo, document, voice, video, sticker, location, contact)
- `edited_message` updates (not handled)

---

## Phase 3 — Message Processing Pipeline (Mostly Shared)

After extraction, the pipeline runs. At this point the flow is almost identical to WebChat.

```
_run_message_pipeline(
    db, workspace_id, channel_id, message_data,
    channel_type="telegram",
    telegram_context={"bot_token": <decrypted>, "chat_id": 987654321}
)
    │
    ├─ 1. Look up Channel and Workspace
    │
    ├─ 2. process_incoming_message()  ← SHARED with WebChat
    │      │
    │      ├─ Maintenance mode check
    │      ├─ Message deduplication (external_message_id = "42")
    │      │      └─ DUPLICATE → return silently, HTTP 200 to Telegram
    │      ├─ Tier quota check
    │      ├─ Get or create Contact (workspace_id + channel_id + "987654321")
    │      ├─ Contact blocked? → store message, return silently
    │      ├─ Get or create Conversation (status="active")
    │      ├─ Business hours check
    │      ├─ Store Message(role="customer", channel_type="telegram", external_message_id="42")
    │      └─ Fire webhooks: conversation.created, message.received [async]
    │
    ├─ 3. notify_new_message()  ← notifies AGENT dashboard via WebSocket (same as WebChat)
    │      └─ Agents see new message in their inbox in real-time
    │
    └─ 4. Continue to Phase 4: Routing
```

**Key difference from WebChat at this stage:**
- WebChat: Has a `session_token` used for customer-side WebSocket delivery
- Telegram: Has a `telegram_context` dict with `bot_token` + `chat_id` used for Bot API replies
- Agent-side WebSocket notifications are identical

---

## Phase 4 — Routing Decision (Fully Shared)

The routing logic is **byte-for-byte identical** to WebChat. The system reads workspace config and picks a path.

```
Read workspace config
    │
    ├─ ai_enabled == False
    │      ├─ agents_enabled == True  → Scenario B (Direct Routing)
    │      └─ agents_enabled == False → Scenario A (Silent Reception)
    │
    └─ ai_enabled == True
           ├─ meta.ai_mode == "ai_agent" → Scenario C (AI Agent Mode)
           └─ meta.ai_mode == "rag"      → Scenario D (RAG Mode)
```

See [Configuration Flags](chat-widget-message-flow.md#configuration-flags) — all flags are workspace-level and apply to all channels equally.

---

## Scenario A — No AI, No Agents (Silent Reception)

**Config:** `ai_enabled=False`, `agents_enabled=False`

```
Telegram message arrives
    │
    └─ Phase 1–3 run (store message, notify agents)
    │
    └─ No reply generated
       No escalation triggered
       HTTP 200 returned to Telegram
       Telegram user sees: nothing (no bot reply)
```

Identical to WebChat Scenario A. The customer just gets no response.

---

## Scenario B — No AI, Agents Enabled (Direct Routing)

**Config:** `ai_enabled=False`, `agents_enabled=True`

```
Telegram message arrives
    │
    └─ Phases 1–3 run
    │
    └─ EscalationRouter.process_escalation(reason="direct_routing")
           │
           ├─ conversation.status = "escalated"
           ├─ Create system message
           ├─ Agent assignment (FIFO or rules)
           ├─ Build acknowledgment text (workspace.escalation_message_with_agents etc.)
           │
           └─ TELEGRAM REPLY:
                  send_telegram_message(
                      bot_token=telegram_context["bot_token"],
                      chat_id=telegram_context["chat_id"],
                      text=ack_text
                  )
                  POST https://api.telegram.org/bot{token}/sendMessage
                       └─ Telegram delivers to user's chat

           ├─ Notify agents: notify_escalation() [WebSocket]
           └─ Fire webhook: conversation.escalated [async]

Telegram user receives: acknowledgment message in Telegram app
Conversation status: "escalated" or "agent"
```

---

## Scenario C — AI Agent Mode

**Config:** `ai_enabled=True`, `meta.ai_mode="ai_agent"`

```
Telegram message arrives
    │
    └─ Phases 1–3 run
    │
    └─ ai_agent_runner.run()   ← SHARED with WebChat, identical logic
           │
           ├─ Find assigned AIAgent for this channel
           │      └─ Not found / inactive → fall to Scenario D (RAG)
           │
           ├─ Check is_active and NOT is_draft
           ├─ Get/create AIAgentConversation session
           ├─ Check max_turns limit
           │      └─ Exceeded → escalate (see Escalation below)
           ├─ Load last 50 messages
           ├─ Build tool schemas
           ├─ Trim to token_budget
           ├─ Call LLM (temperature=0.3)
           ├─ Execute tool calls if requested
           ├─ Log tokens
           ├─ Increment turn_count
           └─ Check for ESCALATE: prefix
                  └─ Present → escalate
    │
    ├─ If NOT escalated:
    │      ├─ Create Message(role="assistant")
    │      │
    │      └─ TELEGRAM REPLY:
    │             send_telegram_message(
    │                 bot_token=telegram_context["bot_token"],
    │                 chat_id=telegram_context["chat_id"],
    │                 text=agent_reply_text
    │             )
    │
    └─ If escalated:
           └─ → Escalation Processing (see below)

Telegram user receives: AI agent reply in Telegram app
```

Sub-scenarios are identical to WebChat Scenario C. See [chat-widget-message-flow.md](chat-widget-message-flow.md#scenario-c--ai-agent-mode) for the full table.

---

## Scenario D — RAG Mode (Default AI)

**Config:** `ai_enabled=True`, `meta.ai_mode="rag"` (or AI agent fell through)

```
Telegram message arrives
    │
    └─ Phases 1–3 run
    │
    ├─ AUTO-ESCALATION CHECK (if auto_escalation_enabled == True)
    │      └─ EscalationClassifier.classify_message()  ← SHARED
    │             ├─ Keyword detection (defaults or workspace.escalation_keywords)
    │             ├─ LLM classification
    │             ├─ Sensitivity threshold (low=0.78 / medium=0.60 / high=0.42)
    │             └─ Should escalate? → Escalation Processing (below)
    │
    └─ If NOT escalated → RAG PIPELINE  ← SHARED
           │
           └─ RAGEngine.process_rag_query()
                  ├─ Context gathering (conversation history + persona)
                  ├─ Small-talk detection → skip search if match
                  ├─ Query rewriting (LLM, if history exists)
                  ├─ Embedding (cached, LRU 512 entries)
                  ├─ Hybrid search (vector + BM25 + RRF, top-20)
                  ├─ MMR re-ranking (top-5)
                  ├─ Neighbor expansion
                  └─ LLM generation (temperature=0.4, max 300 tokens)
           │
           ├─ If no chunks found (used_fallback=True):
           │      ├─ auto_escalation_enabled → Escalation Processing
           │      └─ not enabled → use workspace.fallback_msg
           │
           └─ TELEGRAM REPLY:
                  send_telegram_message(
                      bot_token=telegram_context["bot_token"],
                      chat_id=telegram_context["chat_id"],
                      text=rag_response_text
                  )

Telegram user receives: RAG-generated reply in Telegram app
```

The RAG pipeline is 100% shared. See [RAG Pipeline: Deep Dive](chat-widget-message-flow.md#rag-pipeline-deep-dive) for full step-by-step detail.

---

### Escalation Processing (Any Scenario That Escalates)

Escalation logic is **fully shared** with WebChat. The only difference is the reply delivery method.

```
EscalationRouter.process_escalation(...)
    ├─ conversation.status = "escalated"
    ├─ Create system message
    ├─ Assign agent (FIFO or rules)
    ├─ Build acknowledgment text
    │
    ├─ TELEGRAM REPLY (acknowledgment to customer):
    │      send_telegram_message(bot_token, chat_id, ack_text)
    │
    ├─ Notify agents: notify_escalation() [WebSocket]
    ├─ If no agents + escalation_email_enabled: send email to owner
    └─ Fire webhook: conversation.escalated [async]
```

For escalation reasons, sensitivity levels, and agent assignment rules, see [Escalation Processing: Deep Dive](chat-widget-message-flow.md#escalation-processing-deep-dive).

---

## How Replies Are Delivered (Telegram Bot API)

**File:** `app/services/telegram_sender.py`

```
send_telegram_message(bot_token, chat_id, text)
    │
    ├─ Build request:
    │      POST https://api.telegram.org/bot{bot_token}/sendMessage
    │      Headers: Content-Type: application/json
    │      Body: {
    │          "chat_id": chat_id,
    │          "text": text,
    │          "parse_mode": "HTML"
    │      }
    │      Timeout: 10 seconds
    │
    ├─ If response status != 200 OR json.ok == false:
    │      └─ HTML parse error? → RETRY without parse_mode:
    │             POST same endpoint without "parse_mode" field
    │
    └─ Return: True (sent) / False (failed)
               └─ Failure is logged but NOT retried beyond the one HTML fallback
```

**What this means:**
- Reply is a direct HTTP call to Telegram servers
- There is no persistent connection — each reply is a fresh HTTP request
- Bot token is decrypted on-the-fly from `Channel.config` for each request
- HTML formatting is attempted first; if Telegram rejects it (malformed tags), plain text is sent

**Contrast with WebChat:**
- WebChat uses `notify_customer_new_message()` which publishes to Redis pub/sub → WebSocket push
- Telegram bot API is simpler but has no delivery acknowledgment

---

## Agent/Owner Sending a Message

When a human agent replies to the customer from the dashboard:

```
POST /api/conversations/{conversation_id}/messages
    (body: {content: "Hello, I'm here to help..."})
    │
    ├─ Determine channel_type from Conversation
    │
    └─ channel_type == "telegram":
           ├─ Get Contact (has external_id = Telegram user_id)
           ├─ Get Channel (has encrypted bot_token)
           ├─ Decrypt: bot_token = decrypt_credential(channel.config["bot_token"])
           ├─ send_telegram_message(
           │      bot_token=bot_token,
           │      chat_id=contact.external_id,  ← used as chat_id
           │      text=request.content
           │  )
           └─ Create Message(role="agent") in DB

Telegram user receives: agent's message in Telegram app
```

**Note:** `contact.external_id` (Telegram user_id) is used as `chat_id`. This works perfectly for private chats because in Telegram, `private chat_id == user_id`. It will not work correctly for group conversations (not currently supported).

---

## Business Hours, Maintenance Mode, Blocking

These are all handled in Phase 3 (`process_incoming_message()`) and are identical to WebChat.

| Condition | Telegram Behaviour |
|-----------|-------------------|
| Maintenance mode | No message stored, no reply, HTTP 200 returned |
| Rate limited | 429 (but Telegram always gets HTTP 200 anyway to avoid retries) |
| Duplicate message | Return silently (deduplicated by `message_id`) |
| Contact blocked | Message stored, no reply, no escalation |
| Outside hours (pause) | Reply sent via `send_telegram_message()`, conversation paused |
| Outside hours (continue) | Informational reply sent, pipeline continues normally |
| Quota exceeded | No processing, error logged |

---

## Supported & Unsupported Message Types

This is the most significant limitation vs WhatsApp or WebChat.

| Message Type | Supported | Notes |
|---|---|---|
| Text | ✅ Yes | Full pipeline |
| Photo | ❌ No | Extraction returns `None`, silently dropped |
| Document/File | ❌ No | Silently dropped |
| Voice/Audio | ❌ No | Silently dropped |
| Video | ❌ No | Silently dropped |
| Sticker | ❌ No | Silently dropped |
| Location | ❌ No | Silently dropped |
| Contact | ❌ No | Silently dropped |
| Edited message | ❌ No | `edited_message` key not read; silently dropped |
| Inline button callbacks | ❌ No | `callback_query` key not read |
| Channel posts | ❌ No | `channel_post` key not read |
| Group messages | ⚠️ Partially | Received but reply goes to `user_id` not `group_chat_id` |

When a user sends a photo (with or without a caption), the bot receives it but produces no reply — the message is silently dropped at extraction.

---

## Delivery Status Tracking

**Telegram has no delivery receipt mechanism.**

| Status Field | WebChat | Telegram |
|---|---|---|
| `delivery_status` | Tracked (sent/delivered/read) | NULL — not used |
| `sent_at` | Set when message saved | Not set |
| `delivered_at` | Updated via webhook | Never updated |
| `read_at` | Updated via webhook | Never updated |

`send_telegram_message()` returns `True` (API accepted the message) or `False` (API error). There is no callback when the user actually receives or reads the message. This is a Telegram platform limitation — their Bot API does not offer delivery receipts.

---

## Webhook Retry Behaviour

Telegram will retry webhook delivery for up to **24 hours** if the server returns a non-2xx response.

```
Processing fails mid-pipeline (exception thrown)
    │
    └─ Exception caught and logged
    └─ HTTP 200 {"ok": True} still returned to Telegram
       ← This prevents any retry

Processing succeeds
    └─ HTTP 200 {"ok": True} returned to Telegram
```

The downside: if a message fails to process (e.g., database error), Telegram will NOT retry it — the 200 prevents that. The message is lost. This is a deliberate trade-off to avoid infinite retry loops.

---

## Edited Messages

```
User edits a sent message in Telegram
    │
    └─ Telegram sends: POST /webhooks/telegram/{token}
       Body: {
         "update_id": 99999,
         "edited_message": { ... }   ← NOT "message"
       }
    │
    └─ webhook_handlers._extract_telegram_message()
           └─ Checks: webhook_data.get("message")
              └─ "edited_message" key is NEVER checked
                 → Returns None
    │
    └─ Pipeline never runs
       No DB update
       No reply to user
       HTTP 200 returned to Telegram

Result: Edits are silently ignored.
```

---

## Deduplication

**Key:** `Message.external_message_id = str(telegram_message_id)`

Telegram `message_id` values are unique within a single chat but NOT globally. The deduplication check is:

```sql
SELECT * FROM messages
WHERE external_message_id = '42'
AND workspace_id = '{workspace_id}'
```

This is per-workspace, not per-chat. Theoretical edge case: if two different Telegram chats both produce `message_id=42` in the same workspace around the same time, the second would be dropped as a duplicate. In practice this is extremely rare but worth knowing.

---

## Contact & Conversation Identity

```
Telegram User 987654321 sends message to bot
    │
    ├─ Contact lookup key: (workspace_id, channel_id, "987654321")
    │      └─ Contact.external_id = "987654321"  ← permanent Telegram user ID
    │
    ├─ Conversation: linked to Contact + Channel
    │
    └─ Reply routing:
           telegram_context["chat_id"] = 987654321   (from message.chat.id)
           contact.external_id         = "987654321"  (from message.from.id)

In private chats: chat_id == user_id (both are 987654321)
In group chats: chat_id != user_id (chat_id is negative group ID)
                Current code uses chat_id from telegram_context for bot replies,
                but uses contact.external_id (user_id) for agent replies —
                this inconsistency means agent replies in groups may fail.
```

---

## Credential Storage & Security

```
Channel creation:
    bot_token = "7xxx:AAA..."
    └─ encrypt_credential(bot_token)
       └─ Stored as Channel.config = {"bot_token": "<CIPHERTEXT>"}

At webhook time:
    └─ Decrypt once: decrypt_credential(channel.config["bot_token"])
    └─ Used for send_telegram_message() calls
    └─ Never logged, never stored in plaintext

Webhook verification:
    └─ TELEGRAM_SECRET_TOKEN env var (optional)
       └─ If set: Telegram includes it in X-Telegram-Bot-Api-Secret-Token header
       └─ Server verifies with secrets.compare_digest() (timing-safe)
       └─ Mismatch: exception raised, no processing, HTTP 200 returned
```

---

## Complete Decision Tree

```
Telegram user sends message
    │
    └─ POST /webhooks/telegram/{bot_token}
           │
           ├─ Secret token verification (if TELEGRAM_SECRET_TOKEN set)
           │      └─ FAIL → log, return {"ok":True}, stop
           │
           ├─ Extract message from payload
           │      └─ No "message" key → return {"ok":True}, stop
           │      └─ No text / empty text → return {"ok":True}, stop
           │
           ├─ Look up Channel by bot_token → Workspace
           │      └─ Not found → return {"ok":True}, stop
           │
           ├─ process_incoming_message()
           │      ├─ Maintenance mode → no storage, return {"ok":True}, stop
           │      ├─ Duplicate message_id → return {"ok":True}, stop
           │      ├─ Quota exceeded → return {"ok":True}, stop
           │      ├─ Contact blocked → store message, return {"ok":True}, stop
           │      ├─ Outside hours (pause) → send_telegram_message(hours_msg), pause, stop
           │      ├─ Outside hours (continue) → send_telegram_message(hours_msg), continue
           │      └─ Store customer message, fire webhooks
           │
           ├─ notify_new_message() → agent WebSocket event
           │
           ├─ ai_enabled == False
           │      ├─ agents_enabled == True → Scenario B
           │      │      └─ EscalationRouter.process_escalation("direct_routing")
           │      │         └─ send_telegram_message(ack_text)
           │      └─ agents_enabled == False → Scenario A (no reply)
           │
           └─ ai_enabled == True
                  ├─ ai_mode == "ai_agent"
                  │      └─ ai_agent_runner.run()
                  │             ├─ Agent missing/inactive → fall to RAG
                  │             ├─ max_turns exceeded → Escalation
                  │             ├─ ESCALATE: prefix → Escalation
                  │             └─ Normal → send_telegram_message(reply)
                  │
                  └─ ai_mode == "rag" (or agent fell through)
                         │
                         ├─ auto_escalation_enabled == True
                         │      └─ EscalationClassifier.classify_message()
                         │             ├─ Keyword or LLM says escalate → Escalation
                         │             └─ Not escalated → RAG Pipeline
                         │
                         └─ auto_escalation_enabled == False → RAG Pipeline directly
                                │
                                └─ RAGEngine.process_rag_query()
                                       ├─ Small-talk → direct LLM answer
                                       ├─ Results found → send_telegram_message(rag_reply)
                                       └─ No results (used_fallback):
                                              ├─ escalation on → Escalation
                                              └─ escalation off → send_telegram_message(fallback_msg)

ESCALATION PROCESSING (any path):
    ├─ process_escalation()
    ├─ send_telegram_message(ack_text)
    ├─ notify_escalation() [agent WebSocket]
    ├─ No agents + email enabled → send email to owner
    └─ trigger_event("conversation.escalated") [async]

ALWAYS return HTTP 200 {"ok": True} at the end
```

---

## Database State Changes Per Scenario

Identical to WebChat except `channel_type="telegram"` and `external_message_id` is set on customer message rows.

| Scenario | Message Rows Created | Conversation Status | Notes |
|----------|---------------------|--------------------|----|
| No text / media message | 0 | N/A | Dropped at extraction |
| Edited message | 0 | N/A | Dropped at extraction |
| Maintenance | 0 | unchanged | Nothing stored |
| Duplicate | 0 | unchanged | Silently ignored |
| Blocked | 1 (customer) | unchanged | No reply |
| Outside hours (pause) | 2 (customer + system) | "paused" | Reply via Bot API |
| Outside hours (continue) | 2+ | normal flow | Bot API sends hours msg + continues |
| Scenario A | 1 (customer) | "active" | No reply |
| Scenario B | 3 (customer + system + assistant ack) | "escalated"/"agent" | Bot API sends ack |
| Scenario C (normal) | 2 (customer + assistant) | "active" | Bot API sends reply |
| Scenario C (escalated) | 3 (customer + system + assistant ack) | "escalated" | Bot API sends ack |
| Scenario D (RAG success) | 2 (customer + assistant) | "active" | Bot API sends reply |
| Scenario D (RAG fallback, escalate) | 3 (customer + system + assistant ack) | "escalated" | Bot API sends ack |
| Scenario D (RAG fallback, no escalate) | 2 (customer + fallback) | "active" | Bot API sends fallback |
| Scenario D (classifier escalates) | 3 (customer + system + assistant ack) | "escalated" | Bot API sends ack |

---

## Shared vs Unique — Full Comparison Table

| Feature | WebChat | Telegram | Shared? |
|---------|---------|----------|---------|
| Entry point | `POST /api/webchat/send` | `POST /webhooks/telegram/{token}` | No |
| Initiator | Customer HTTP call | Telegram platform HTTP call | No |
| Auth method | Session token in body | Secret token in header | No |
| Contact identity | Session UUID (per browser tab) | Telegram user_id (permanent) | No |
| Reply delivery | WebSocket push | Telegram Bot API HTTP POST | No |
| HTML formatting | No | Yes (with plain-text fallback) | No |
| Delivery tracking | DB fields | None | No |
| Webhook retry handling | N/A | Always HTTP 200 | No |
| Media support | Text + file uploads | Text only | No |
| Edited messages | N/A | Not supported | No |
| Group chat support | N/A | Partial (broken for agent replies) | No |
| Maintenance mode | `process_incoming_message()` | Same | **Yes** |
| Rate limiting | Per session_token | Per session/bot | Partially |
| Deduplication | `external_message_id` | Same mechanism | **Yes** |
| Tier quota check | `TierManager` | Same | **Yes** |
| Contact creation | `process_incoming_message()` | Same | **Yes** |
| Conversation creation | `process_incoming_message()` | Same | **Yes** |
| Business hours | `process_incoming_message()` | Same | **Yes** |
| Message storage | `process_incoming_message()` | Same | **Yes** |
| Routing decision | Workspace config flags | Same flags | **Yes** |
| RAG pipeline | `RAGEngine` | Same | **Yes** |
| Auto-escalation | `EscalationClassifier` | Same | **Yes** |
| Escalation processing | `EscalationRouter` | Same | **Yes** |
| Agent assignment | FIFO + rules | Same | **Yes** |
| AI Agent mode | `AIAgentRunner` | Same | **Yes** |
| Tool calling | `ToolExecutor` | Same | **Yes** |
| Token tracking | `AIAgentTokenTracker` | Same | **Yes** |
| Agent WebSocket events | `notify_new_message()` etc. | Same | **Yes** |
| Outbound webhooks | `trigger_event()` | Same | **Yes** |

**Summary:** Everything from the routing decision inward is 100% shared. The differences are entirely at the edges — how the message arrives and how the reply is dispatched.

---

*Last updated: 2026-05-07*
