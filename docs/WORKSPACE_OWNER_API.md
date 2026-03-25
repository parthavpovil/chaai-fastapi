# Workspace Owner — API & WebSocket Reference

> **Role**: The workspace owner is the primary user of the platform. They register, configure the workspace, manage agents and channels, handle conversations, and control all billing and settings.
>
> **Base URL**: `https://api.yourdomain.com`
> **Auth Header**: `Authorization: Bearer <access_token>`

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Workspace](#2-workspace)
3. [Agents](#3-agents)
4. [Conversations](#4-conversations)
5. [Channels](#5-channels)
6. [Documents (RAG / Knowledge Base)](#6-documents-rag--knowledge-base)
7. [Contacts](#7-contacts)
8. [Canned Responses](#8-canned-responses)
9. [Flows](#9-flows)
10. [WhatsApp Templates](#10-whatsapp-templates)
11. [Broadcasts (WhatsApp)](#11-broadcasts-whatsapp)
12. [API Keys](#12-api-keys)
13. [Billing & Subscription](#13-billing--subscription)
14. [Assignment Rules](#14-assignment-rules)
15. [Outbound Webhooks](#15-outbound-webhooks)
16. [Business Hours](#16-business-hours)
17. [AI Agents](#17-ai-agents)
18. [Metrics & CSAT](#18-metrics--csat)
19. [WebSocket — Owner Dashboard](#19-websocket--owner-dashboard)
20. [Tier Limits Reference](#20-tier-limits-reference)
21. [Error Codes](#21-error-codes)

---

## 1. Authentication

### How it works

The owner uses email/password login and receives a short-lived JWT access token. This token is sent in the `Authorization` header on every request. The token contains the user's role (`owner`), workspace ID, and email.

For programmatic access (Growth+ tier), API keys prefixed with `csk_` can be used instead of JWT tokens.

---

### `POST /api/auth/register`

Creates a new user account and workspace in one step.

**No auth required.**

**Request Body**:
```json
{
  "email": "owner@company.com",
  "password": "securepassword123",
  "business_name": "Acme Corp"
}
```

**Response `200`**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "uuid",
    "email": "owner@company.com",
    "is_active": true,
    "created_at": "2026-01-01T00:00:00Z"
  },
  "workspace": {
    "id": "uuid",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "tier": "free",
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

**What happens internally**:
- User record is created with bcrypt-hashed password
- A workspace is created with the `free` tier
- Default platform settings are initialized
- A JWT token is returned immediately (no email verification step)

---

### `POST /api/auth/login`

Authenticates a workspace owner and returns a fresh token.

**No auth required.**

**Request Body**:
```json
{
  "email": "owner@company.com",
  "password": "securepassword123"
}
```

**Response `200`**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "uuid",
    "email": "owner@company.com",
    "is_active": true,
    "last_login": "2026-03-25T10:00:00Z",
    "created_at": "2026-01-01T00:00:00Z"
  },
  "workspace": {
    "id": "uuid",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "tier": "starter",
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

**Notes**:
- Only works for accounts with `role: owner`. Agents must use `/api/auth/agent-login`
- Updates `user.last_login` on success
- Returns `401` if credentials are wrong or account is inactive

---

### `GET /api/auth/me`

Returns the currently authenticated user's info and workspace.

**Auth required.**

**Response `200`**:
```json
{
  "user": {
    "id": "uuid",
    "email": "owner@company.com",
    "is_active": true,
    "last_login": "2026-03-25T10:00:00Z",
    "created_at": "2026-01-01T00:00:00Z"
  },
  "workspace": {
    "id": "uuid",
    "name": "Acme Corp",
    "slug": "acme-corp",
    "tier": "growth",
    "fallback_msg": "Sorry, I couldn't find an answer.",
    "alert_email": "alerts@company.com",
    "agents_enabled": true,
    "escalation_keywords": ["refund", "cancel", "urgent"],
    "escalation_sensitivity": "medium",
    "escalation_email_enabled": true,
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

**Use case**: Call this on app load to restore session state and get workspace config.

---

### `POST /api/auth/refresh`

Refreshes the JWT token before it expires.

**No auth required (token passed in body).**

**Request Body**:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response `200`**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Notes**:
- Call this ~5 minutes before the token expires to silently keep the session alive
- Preserves user ID, email, role, and workspace_id from the original token
- Returns `401` if the token is already expired or invalid

---

## 2. Workspace

### `GET /api/workspace/overview`

Returns a dashboard summary with real-time usage stats.

**Auth required (owner).**

**Response `200`**:
```json
{
  "workspace_id": "uuid",
  "name": "Acme Corp",
  "tier": "growth",
  "conversations_today": 42,
  "messages_this_month": 3821,
  "tier_quota_remaining": 6179,
  "tier_quota_total": 10000
}
```

**Use case**: Show on the main dashboard — current tier, daily conversation count, monthly message burn rate.

---

### `PUT /api/workspace/settings`

Updates workspace-level configuration including escalation and fallback behavior.

**Auth required (owner).**

**Request Body** (all fields optional):
```json
{
  "fallback_msg": "I'm not sure how to help with that. Please contact support@company.com.",
  "alert_email": "support@company.com",
  "agents_enabled": true,
  "escalation_keywords": ["refund", "cancel", "complaint", "urgent", "manager"],
  "escalation_sensitivity": "medium",
  "escalation_email_enabled": true
}
```

| Field | Type | Description |
|---|---|---|
| `fallback_msg` | string (max 500) | Message shown when AI can't answer |
| `alert_email` | email | Email address that receives escalation alerts |
| `agents_enabled` | boolean | Whether human agents can be assigned to conversations |
| `escalation_keywords` | string[] | Keywords in customer messages that trigger escalation |
| `escalation_sensitivity` | `"low"` \| `"medium"` \| `"high"` | How aggressively AI classifies messages as escalation-worthy |
| `escalation_email_enabled` | boolean | Send email to `alert_email` when a conversation is escalated |

**Response `200`**: Returns updated workspace object (same shape as `GET /api/auth/me` workspace field).

---

### `GET /api/workspace/ai-config`

Returns the current AI provider and model configuration.

**Auth required (owner). Tier: Growth+.**

**Response `200`**:
```json
{
  "ai_provider": "openai",
  "ai_model": "gpt-4o",
  "has_api_key": true
}
```

**Notes**:
- `has_api_key` is `true`/`false` — the raw key is never returned
- On free/starter, this endpoint returns `402`

---

### `PUT /api/workspace/ai-config`

Updates the AI model used for auto-replies.

**Auth required (owner). Tier: Growth+.**

**Request Body**:
```json
{
  "ai_provider": "openai",
  "ai_model": "gpt-4o",
  "ai_api_key": "sk-..."
}
```

| `ai_provider` | Valid `ai_model` examples |
|---|---|
| `google` | `gemini-1.5-pro`, `gemini-2.0-flash` |
| `openai` | `gpt-4o`, `gpt-4o-mini` |
| `groq` | `llama-3.3-70b-versatile` |
| `anthropic` | `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` |

**Response `200`**: Returns `{ ai_provider, ai_model, has_api_key: true }`.

---

### `GET /api/workspace/ai-pipeline`

Returns the full AI pipeline mode and model config.

**Auth required (owner).**

**Response `200`**:
```json
{
  "ai_mode": "rag",
  "ai_provider": "openai",
  "ai_model": "gpt-4o",
  "has_api_key": true
}
```

| `ai_mode` | Description |
|---|---|
| `rag` | AI answers using your uploaded documents as context |
| `ai_agent` | AI uses a configured AI Agent with tools and instructions |

---

### `PUT /api/workspace/ai-pipeline`

Configures the AI mode, provider, and model together.

**Auth required (owner). Tier: Growth+.**

**Request Body**:
```json
{
  "ai_mode": "rag",
  "ai_provider": "anthropic",
  "ai_model": "claude-sonnet-4-6",
  "ai_api_key": "sk-ant-..."
}
```

**Response `200`**: Updated pipeline config.

---

## 3. Agents

### `POST /api/agents/invite`

Invites a new human agent to the workspace. Sends an invitation email.

**Auth required (owner).**

**Request Body**:
```json
{
  "email": "agent@company.com",
  "name": "Sarah Jones"
}
```

**Response `201`**:
```json
{
  "id": "uuid",
  "email": "agent@company.com",
  "name": "Sarah Jones",
  "invitation_token": "abc123...",
  "invitation_expires_at": "2026-04-01T10:00:00Z",
  "invited_at": "2026-03-25T10:00:00Z"
}
```

**What happens internally**:
- Agent record created with `is_active: false` and a 7-day invitation token
- Invitation email sent to the agent's email address with a link
- Counts against your tier's agent limit

**Tier limits**: Free=0 agents, Starter=2, Growth=5, Pro=unlimited.

---

### `GET /api/agents/`

Lists all agents in the workspace.

**Auth required (owner).**

**Query params**:
- `include_inactive` (boolean, default `false`) — include deactivated agents

**Response `200`**:
```json
[
  {
    "id": "uuid",
    "email": "agent@company.com",
    "name": "Sarah Jones",
    "is_active": true,
    "user_id": "uuid",
    "status": "online",
    "invited_at": "2026-03-20T10:00:00Z",
    "accepted_at": "2026-03-21T08:00:00Z",
    "deactivated_at": null
  }
]
```

| `status` | Meaning |
|---|---|
| `online` | Agent is logged in and available |
| `offline` | Agent is logged out or idle |
| `busy` | Agent has marked themselves as busy |

---

### `GET /api/agents/pending`

Lists agents who have been invited but haven't accepted yet.

**Auth required (owner).**

**Response `200`**:
```json
[
  {
    "id": "uuid",
    "email": "newagent@company.com",
    "name": "Tom Smith",
    "invitation_token": "xyz456...",
    "invitation_expires_at": "2026-04-01T10:00:00Z",
    "invited_at": "2026-03-25T10:00:00Z"
  }
]
```

---

### `POST /api/agents/{agent_id}/deactivate`

Deactivates an agent — they can no longer log in or handle conversations.

**Auth required (owner).**

**Response `200`**: Returns updated agent object with `is_active: false` and `deactivated_at` timestamp.

**Side effect**: Broadcasts `agent_status_change` WebSocket event to the workspace.

---

### `POST /api/agents/{agent_id}/activate`

Re-activates a previously deactivated agent.

**Auth required (owner).**

**Response `200`**: Returns updated agent object with `is_active: true`.

**Notes**:
- Checks tier agent limit before activating — returns `402` if limit exceeded
- Broadcasts `agent_status_change` WebSocket event

---

### `POST /api/agents/{agent_id}/resend`

Resends the invitation email with a fresh token (existing token is invalidated).

**Auth required (owner).**

**Response `200`**: Returns new invitation object with updated `invitation_token` and `invitation_expires_at`.

---

### `DELETE /api/agents/{agent_id}`

Deletes a pending invitation. Can only delete agents who haven't accepted yet.

**Auth required (owner).**

**Response `200`**:
```json
{ "message": "Agent invitation deleted successfully" }
```

**Notes**: Returns `400` if the agent has already accepted (has a `user_id`).

---

### `GET /api/agents/stats`

Returns performance statistics for all agents.

**Auth required (owner).**

**Response `200`**:
```json
{
  "total_agents": 5,
  "active_agents": 4,
  "inactive_agents": 1,
  "pending_invitations": 2,
  "tier_info": {
    "tier": "growth",
    "limit": 5,
    "used": 4
  },
  "per_agent": [
    {
      "agent_id": "uuid",
      "name": "Sarah Jones",
      "email": "sarah@company.com",
      "status": "online",
      "conversations_active": 3,
      "conversations_resolved_30d": 47,
      "avg_csat": 4.2
    }
  ]
}
```

---

## 4. Conversations

### `GET /api/conversations/`

Lists conversations with optional filtering and pagination.

**Auth required (owner).**

**Query params**:

| Param | Type | Description |
|---|---|---|
| `status_filter` | string | `active` \| `escalated` \| `agent` \| `resolved` |
| `limit` | int (1-100) | Default: 50 |
| `offset` | int | Pagination offset |

**Response `200`**:
```json
{
  "conversations": [
    {
      "id": "uuid",
      "status": "escalated",
      "contact": {
        "id": "uuid",
        "name": "John Doe",
        "external_id": "CUS-001",
        "channel_type": "webchat",
        "metadata": {}
      },
      "assigned_agent_id": null,
      "assigned_agent_name": null,
      "escalation_reason": "keyword_match",
      "message_count": 8,
      "last_message": {
        "id": "uuid",
        "content": "I want a refund immediately",
        "role": "customer",
        "sender_name": "John Doe",
        "created_at": "2026-03-25T09:45:00Z",
        "metadata": {}
      },
      "created_at": "2026-03-25T09:00:00Z",
      "updated_at": "2026-03-25T09:45:00Z"
    }
  ],
  "total_count": 142,
  "has_more": true
}
```

> **Note on `contact` object**: The contact field in conversation list/detail responses contains `external_id` (your internal customer ID) and `channel_type` — not `email`/`phone`. To get full contact details including email/phone, use `GET /api/contacts/{contact_id}`.
```

**Conversation statuses**:

| Status | Meaning |
|---|---|
| `active` | AI is handling it |
| `escalated` | Flagged for human review, not yet assigned |
| `agent` | Assigned to a human agent |
| `resolved` | Closed |

---

### `GET /api/conversations/{conversation_id}`

Gets a specific conversation with its full message history.

**Auth required (owner or assigned agent).**

**Response `200`**:
```json
{
  "id": "uuid",
  "status": "agent",
  "contact": {
    "id": "uuid",
    "name": "John Doe",
    "external_id": "CUS-001",
    "channel_type": "webchat",
    "metadata": {}
  },
  "assigned_agent_id": "uuid",
  "assigned_agent_name": "Sarah Jones",
  "escalation_reason": "keyword_match",
  "messages": [
    {
      "id": "uuid",
      "content": "I need help with my order",
      "role": "customer",
      "sender_name": "John Doe",
      "created_at": "2026-03-25T09:00:00Z",
      "metadata": {}
    },
    {
      "id": "uuid",
      "content": "I can help with that. What's your order number?",
      "role": "assistant",
      "sender_name": "AI",
      "created_at": "2026-03-25T09:00:05Z",
      "metadata": {}
    },
    {
      "id": "uuid",
      "content": "Let me take over and help you personally.",
      "role": "agent",
      "sender_name": "Sarah Jones",
      "created_at": "2026-03-25T09:10:00Z",
      "metadata": {}
    }
  ],
  "created_at": "2026-03-25T09:00:00Z",
  "updated_at": "2026-03-25T09:10:00Z"
}
```

**Message roles**:
- `customer` — message from the end user
- `assistant` — AI-generated reply
- `agent` — message from a human agent

---

### `GET /api/conversations/stats/summary`

Returns aggregate conversation statistics.

**Auth required (owner).**

**Response `200`**:
```json
{
  "total_conversations": 1024,
  "active_conversations": 18,
  "escalated_conversations": 5,
  "agent_conversations": 3,
  "resolved_conversations": 998
}
```

---

### `GET /api/conversations/my/active`

Returns conversations currently assigned to the authenticated agent (agent-only shortcut).

**Auth required (agent).**

**Response `200`**: Same shape as `GET /api/conversations/` but pre-filtered to the calling agent.

---

### `POST /api/conversations/claim`

Agent claims an escalated conversation. Takes the conversation ID in the request body.

**Auth required (agent only).**

**Request Body**:
```json
{ "conversation_id": "uuid" }
```

**Response `200`**:
```json
{ "message": "Conversation claimed successfully" }
```

**Updates**: Sets `assigned_agent_id`, moves status `escalated` → `agent`.

**Side effect**: Broadcasts `agent_claim` WebSocket event.

---

### `POST /api/conversations/status`

Changes a conversation's status. Takes the conversation ID in the request body.

**Auth required (owner or assigned agent).**

> Owner can update ANY conversation. An agent can only update conversations assigned to them.

**Request Body**:
```json
{
  "conversation_id": "uuid",
  "status": "resolved",
  "note": "Customer issue resolved via phone call"
}
```

**Valid statuses**: `active` | `escalated` | `agent` | `resolved`

**Response `200`**: Returns `{ message: "Status updated" }`.

**Side effects**:
- Broadcasts `conversation_status_change` WebSocket event
- If status is `resolved`, fires `conversation.resolved` outbound webhook

---

### `GET /api/conversations/search`

Full-text search across conversation messages with rich filtering.

**Auth required (owner).**

**Query params**:

| Param | Type | Description |
|---|---|---|
| `q` | string | Full-text search across message content (PostgreSQL tsvector) |
| `contact_name` | string | Filter by contact name (partial match) |
| `channel_type` | string | `webchat` \| `telegram` \| `whatsapp` \| `instagram` |
| `status` | string | `active` \| `escalated` \| `agent` \| `resolved` |
| `date_from` | date | ISO date (e.g. `2026-01-01`) |
| `date_to` | date | ISO date |
| `assigned_agent_id` | uuid | Filter by assigned agent |
| `limit` | int (1-100) | Default 50 |
| `offset` | int | Pagination offset |

**Response `200`**:
```json
{
  "results": [
    {
      "id": "uuid",
      "status": "resolved",
      "channel_type": "webchat",
      "contact_name": "John Doe",
      "created_at": "2026-03-20T09:00:00Z",
      "updated_at": "2026-03-20T09:30:00Z",
      "message_snippet": "...I want a <b>refund</b> for my order..."
    }
  ],
  "total_count": 12,
  "has_more": false
}
```

**Notes**:
- `message_snippet` is an HTML-highlighted excerpt showing where the search term was found — only present when `q` is provided
- Without `q`, it acts as a filtered list

---

### `GET /api/conversations/export`

Exports conversations as a streaming CSV file. Supports the same filters as search.

**Auth required (owner). Tier: Growth+.**

**Query params** (all optional):

| Param | Type | Description |
|---|---|---|
| `q` | string | Full-text search filter |
| `contact_name` | string | Filter by contact name |
| `channel_type` | string | Filter by channel |
| `status` | string | Filter by status |
| `date_from` | date | Start date |
| `date_to` | date | End date |
| `assigned_agent_id` | uuid | Filter by agent |

**Response**: Streaming `text/csv` download with headers:
`conversation_id, contact_name, channel_type, status, created_at, resolved_at, message_count, escalated, assigned_agent_name, csat_rating`

**Notes**: Returns `403` on free/starter tiers.

---

### `GET /api/conversations/{conversation_id}/csat`

Gets the CSAT (customer satisfaction) rating submitted for a specific conversation.

**Auth required (owner).**

**Response `200`** (if rating exists):
```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "rating": 4,
  "comment": "Very helpful, resolved quickly!",
  "submitted_at": "2026-03-25T11:00:00Z"
}
```

**Response `200`** (if no rating submitted): `null`

---

### `POST /api/conversations/{conversation_id}/messages`

Sends an agent message into an existing conversation.

**Auth required (owner or assigned agent).**

**Request Body**:
```json
{
  "content": "Hi John, let me look into this for you right away."
}
```

| Field | Constraint |
|---|---|
| `content` | 1–2000 characters |

**Response `200`**:
```json
{
  "message_id": "uuid",
  "created_at": "2026-03-25T11:00:00Z"
}
```

**Side effect**: Updates `conversation.updated_at`, broadcasts `new_message` WebSocket event.

---

### `POST /api/conversations/{conversation_id}/notes`

Creates an internal note on a conversation. Notes are only visible to agents/owners — never sent to the customer.

**Auth required (owner or assigned agent).**

**Request Body**:
```json
{
  "content": "Customer called in separately and said they're happy to wait until next week."
}
```

**Response `201`**:
```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "content": "Customer called in separately...",
  "created_by_name": "Sarah Jones",
  "created_at": "2026-03-25T11:05:00Z"
}
```

---

### `GET /api/conversations/{conversation_id}/notes`

Lists all internal notes on a conversation.

**Auth required (owner or assigned agent).**

**Response `200`**: Array of note objects (same shape as create response).

---

### `POST /api/conversations/{conversation_id}/messages/{message_id}/feedback`

Submits thumbs-up/down feedback on an AI-generated message (used to improve the model).

**Auth required (owner or agent).**

**Request Body**:
```json
{
  "rating": "positive",
  "comment": "Perfect response, addressed the issue clearly"
}
```

| `rating` | Meaning |
|---|---|
| `positive` | Thumbs up |
| `negative` | Thumbs down |

**Response `201`**: Feedback object.

---

### `GET /api/conversations/{conversation_id}/messages/{message_id}/feedback`

Gets the existing feedback for a message (if any).

**Auth required (owner or agent).**

**Response `200`**: Feedback object or `null`.

---

## 5. Channels

### `POST /api/channels/`

Creates a new communication channel (Telegram, WhatsApp, Instagram, or WebChat).

**Auth required (owner).**

**Request Body**:
```json
{
  "channel_type": "webchat",
  "name": "Website Chat",
  "credentials": {
    "business_name": "Acme Corp",
    "primary_color": "#4F46E5",
    "position": "bottom-right",
    "welcome_message": "Hi! How can we help you today?"
  },
  "is_active": true
}
```

**Credentials by channel type**:

**webchat**:
```json
{
  "business_name": "Your Company",
  "primary_color": "#4F46E5",
  "position": "bottom-right",
  "welcome_message": "Hi! How can we help?"
}
```

**telegram**:
```json
{
  "bot_token": "123456789:ABCdefGHIjklmNOPqrstUVwxyz"
}
```

**whatsapp**:
```json
{
  "phone_number_id": "1234567890",
  "access_token": "EAABwz..."
}
```

**instagram**:
```json
{
  "page_id": "1234567890",
  "access_token": "EAABwz..."
}
```

**Response `201`**:
```json
{
  "id": "uuid",
  "channel_type": "webchat",
  "name": "Website Chat",
  "is_active": true,
  "widget_id": "wgt_abc123",
  "platform_info": {
    "business_name": "Acme Corp",
    "primary_color": "#4F46E5"
  },
  "created_at": "2026-03-25T10:00:00Z",
  "updated_at": "2026-03-25T10:00:00Z"
}
```

**Notes**:
- `widget_id` is only present for `webchat` channels — this is the ID embedded in the chat widget script
- Credentials are encrypted at rest and never returned in full

**Tier limits**: Free=1, Starter=3, Growth=5, Pro=unlimited.

---

### `GET /api/channels/`

Lists all channels.

**Auth required (owner).**

**Response `200`**: Array of channel objects (same shape as create response, without raw credentials).

---

### `GET /api/channels/{channel_id}`

Gets a single channel's details.

**Auth required (owner).**

**Response `200`**: Channel object.

---

### `PUT /api/channels/{channel_id}`

Updates a channel's name or active status.

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "Main Website Chat",
  "is_active": false
}
```

**Response `200`**: Updated channel object.

---

### `DELETE /api/channels/{channel_id}`

Deletes a channel permanently.

**Auth required (owner).**

**Response `200`**:
```json
{ "message": "Channel deleted" }
```

---

### `POST /api/channels/validate/{channel_type}`

Validates channel credentials before creating the channel — useful to surface errors early in the UI.

**Auth required (owner).**

**Path param**: `channel_type` — `telegram` | `whatsapp` | `instagram` | `webchat`

**Request Body**: Same credentials object used in channel creation (e.g. `{ "bot_token": "..." }` for Telegram).

**Response `200`**:
```json
{ "valid": true, "message": "Credentials are valid" }
```

Returns `400` with a descriptive error if credentials are rejected by the platform.

---

### `GET /api/channels/stats/summary`

Returns per-channel message and conversation statistics.

**Auth required (owner).**

**Response `200`**: Object with per-channel stats (message count, conversation count, active status).

---

## 6. Documents (RAG / Knowledge Base)

Documents are uploaded to build the AI's knowledge base. The AI uses them to answer customer questions. This feature is available on Starter+ tiers.

### `POST /api/documents/upload`

Uploads a PDF or TXT file for RAG (Retrieval-Augmented Generation).

**Auth required (owner).**

**Request**: `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | File | PDF or TXT, max 10MB |
| `name` | string (optional) | Custom display name for the document |

**Response `202`** (processing starts asynchronously):
```json
{
  "id": "uuid",
  "name": "Product FAQ",
  "file_path": "https://cdn.r2.example.com/docs/uuid/file.pdf",
  "status": "processing",
  "chunks_count": 0,
  "error_message": null,
  "created_at": "2026-03-25T10:00:00Z"
}
```

**Processing flow**:
1. File uploaded to Cloudflare R2 storage
2. Background job splits document into text chunks
3. Each chunk is embedded (vector) and stored in the database
4. `status` updates from `processing` → `completed` (or `failed`)
5. WebSocket event `document_processing` fires on each status change

**Tier limits**: Free=0, Starter=5, Growth=20, Pro=unlimited.

---

### `GET /api/documents/`

Lists workspace documents with optional status filter.

**Auth required (owner).**

**Query params**:
- `status_filter` — `uploading` | `processing` | `completed` | `failed`
- `limit`, `offset`

**Response `200`**:
```json
{
  "documents": [
    {
      "id": "uuid",
      "name": "Product FAQ",
      "file_path": "https://...",
      "status": "completed",
      "chunks_count": 42,
      "error_message": null,
      "created_at": "2026-03-25T10:00:00Z"
    }
  ],
  "total_count": 8,
  "tier_info": {
    "tier": "growth",
    "limit": 20,
    "used": 8
  }
}
```

---

### `GET /api/documents/{document_id}`

Gets details for a specific document.

**Auth required (owner).**

**Response `200`**: Single document object.

---

### `DELETE /api/documents/{document_id}`

Deletes a document and all its associated chunks from the vector store.

**Auth required (owner).**

**Response `200`**:
```json
{ "message": "Document deleted" }
```

---

### `POST /api/documents/{document_id}/reprocess`

Re-triggers processing on a document that failed or got stuck. Useful after fixing an issue with a corrupt file.

**Auth required (owner).**

**Response `200`**: Updated document object with `status: "processing"`.

---

### `GET /api/documents/stats/summary`

Returns document usage statistics.

**Auth required (owner).**

**Response `200`**:
```json
{
  "total_documents": 8,
  "processing_documents": 1,
  "completed_documents": 6,
  "failed_documents": 1,
  "total_chunks": 312,
  "tier_info": {
    "tier": "growth",
    "limit": 20,
    "used": 8
  }
}
```

---

## 7. Contacts

Contacts are automatically created when a customer first messages through any channel. Owners can manage, tag, block, and export contact data.

### `GET /api/contacts/`

Lists contacts with search and tag filtering.

**Auth required (owner).**

**Query params**:
- `search` — searches name, email, phone
- `tags` — filter by tag (e.g., `?tags=vip`)
- `limit`, `offset`

**Response `200`**:
```json
{
  "contacts": [
    {
      "id": "uuid",
      "external_id": "CUS-001",
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1234567890",
      "tags": ["vip", "enterprise"],
      "custom_fields": {
        "account_id": "ACC-123",
        "region": "US-West"
      },
      "source": "webchat",
      "is_blocked": false,
      "created_at": "2026-01-15T08:00:00Z"
    }
  ],
  "total_count": 524,
  "has_more": true
}
```

---

### `GET /api/contacts/{contact_id}`

Gets a contact's full profile including recent conversation history.

**Auth required (owner).**

**Response `200`**:
```json
{
  "id": "uuid",
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "tags": ["vip"],
  "custom_fields": {},
  "source": "webchat",
  "is_blocked": false,
  "created_at": "2026-01-15T08:00:00Z",
  "recent_conversations": [
    {
      "id": "uuid",
      "status": "resolved",
      "channel_type": "webchat",
      "created_at": "2026-03-20T09:00:00Z",
      "updated_at": "2026-03-20T09:30:00Z"
    }
  ]
}
```

---

### `PATCH /api/contacts/{contact_id}`

Updates a contact's details and tags (partial update — only send fields you want to change).

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "John Doe",
  "email": "john.doe@example.com",
  "phone": "+1234567890",
  "tags": ["vip", "enterprise", "renewal-2026"],
  "custom_fields": {
    "account_tier": "platinum"
  }
}
```

**Response `200`**: Updated contact object.

---

### `POST /api/contacts/{contact_id}/block`

Blocks a contact — their future messages will be ignored.

**Auth required (owner).**

**Response `200`**:
```json
{ "is_blocked": true }
```

---

### `POST /api/contacts/{contact_id}/unblock`

Unblocks a previously blocked contact.

**Auth required (owner).**

**Response `200`**:
```json
{ "is_blocked": false }
```

---

### `DELETE /api/contacts/{contact_id}`

Permanently deletes a contact and all their associated conversations (GDPR compliance).

**Auth required (owner).**

**Response `200`**:
```json
{ "message": "Contact deleted" }
```

---

## 8. Canned Responses

Pre-written message templates that agents can quickly insert during a conversation.

### `POST /api/canned-responses/`

Creates a new canned response.

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "Refund Policy",
  "content": "Our refund policy allows returns within 30 days of purchase. Please provide your order number and we'll process the refund within 3-5 business days.",
  "shortcut": "/refund"
}
```

| Field | Type | Description |
|---|---|---|
| `name` | string | Display name for the template |
| `content` | string (max 5000) | The actual message text |
| `shortcut` | string (max 50, optional) | Quick-access shortcut code (e.g., `/refund`) |

**Response `201`**: Canned response object with `id`, `name`, `content`, `shortcut`, `created_at`, `updated_at`.

**Tier limits**: Free=0, Starter=10, Growth=50, Pro=unlimited.

---

### `GET /api/canned-responses/`

Lists all canned responses.

**Auth required (owner).**

**Response `200`**: Array of canned response objects.

---

### `PUT /api/canned-responses/{response_id}`

Updates a canned response.

**Auth required (owner).**

**Request Body**: Same fields as create (all optional).

**Response `200`**: Updated canned response object.

---

### `DELETE /api/canned-responses/{response_id}`

Deletes a canned response.

**Auth required (owner).**

**Response `200`**: `{ "message": "Deleted" }`

---

## 9. Flows

Flows are automated conversation sequences triggered by keywords, manual trigger, or AI detection.

### `POST /api/flows/`

Creates a new conversation flow.

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "Refund Request Flow",
  "trigger_type": "keyword",
  "trigger_keywords": ["refund", "money back", "return"],
  "is_active": true,
  "steps": {
    "start": {
      "type": "message",
      "content": "I see you'd like a refund. Let me help.",
      "next": "ask_order"
    },
    "ask_order": {
      "type": "input",
      "prompt": "Please provide your order number.",
      "next": "confirm"
    },
    "confirm": {
      "type": "message",
      "content": "Got it! I'll escalate this to our team.",
      "next": null
    }
  }
}
```

| `trigger_type` | Description |
|---|---|
| `keyword` | Triggers when any of `trigger_keywords` appears in a message |
| `manual` | Only triggered manually by an agent |
| `ai_detected` | AI detects the intent and triggers the flow |

**Response `201`**: Flow object with all fields.

---

### `GET /api/flows/`

Lists all flows.

**Auth required (owner).**

**Response `200`**: Array of flow objects.

---

### `GET /api/flows/{flow_id}`

Gets a specific flow.

**Auth required (owner).**

**Response `200`**: Flow object.

---

### `PUT /api/flows/{flow_id}`

Updates a flow.

**Auth required (owner).**

**Request Body**: Same fields as create (all optional).

**Response `200`**: Updated flow object.

---

### `DELETE /api/flows/{flow_id}`

Deletes a flow.

**Auth required (owner).**

---

### `POST /api/flows/{flow_id}/duplicate`

Creates a copy of an existing flow. Useful for creating variations without rebuilding from scratch.

**Auth required (owner).**

**Response `201`**: New flow object (copy) with a new `id` and name suffixed with "Copy".

---

### `GET /api/flows/{flow_id}/stats`

Returns execution statistics for a flow.

**Auth required (owner).**

**Response `200`**: Trigger count, completion rate, drop-off points per step.

---

## 10. WhatsApp Templates

WhatsApp Business requires pre-approved message templates for outbound messages.

### `POST /api/templates/`

Creates a new WhatsApp message template.

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "order_confirmation",
  "category": "UTILITY",
  "language": "en",
  "header_type": "TEXT",
  "header_content": "Order Confirmation",
  "body": "Hi {{1}}, your order #{{2}} has been confirmed. Expected delivery: {{3}}.",
  "footer": "Reply STOP to unsubscribe",
  "buttons": [
    { "type": "URL", "text": "Track Order", "url": "https://track.example.com/{{1}}" }
  ]
}
```

| `category` | Use case |
|---|---|
| `MARKETING` | Promotions, offers |
| `UTILITY` | Order confirmations, alerts, updates |
| `AUTHENTICATION` | OTP, login verification |

**Response `201`**: Template object with `meta_submission_status: "pending"`.

---

### `GET /api/templates/`

Lists all WhatsApp templates.

**Auth required (owner).**

**Response `200`**: Array of template objects.

---

### `GET /api/templates/{template_id}`

Gets a specific template.

**Auth required (owner).**

---

### `PUT /api/templates/{template_id}`

Updates a template (only allowed before Meta submission).

**Auth required (owner).**

---

### `DELETE /api/templates/{template_id}`

Deletes a WhatsApp template.

**Auth required (owner).**

**Response `204` No Content.**

---

### `POST /api/templates/{template_id}/submit`

Submits the template to Meta for approval. Once submitted, it cannot be edited until reviewed.

**Auth required (owner).**

**Response `200`**: Template object with updated `meta_submission_status`.

**Submission statuses**: `pending` → `approved` | `rejected`

---

### `GET /api/templates/{template_id}/preview`

Returns a rendered preview of the template with sample variable substitutions.

**Auth required (owner).**

**Response `200`**: Rendered template content with placeholders filled in with example values.

---

## 11. Broadcasts (WhatsApp)

Send bulk WhatsApp messages to contacts using approved templates.

### `POST /api/broadcasts/`

Creates a new broadcast campaign.

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "March Promotion",
  "template_id": "uuid",
  "variable_mapping": {
    "1": "first_name",
    "2": "promo_code"
  },
  "audience_type": "tag",
  "audience_filter": {
    "tags": ["newsletter"]
  },
  "scheduled_at": "2026-03-30T09:00:00Z"
}
```

| `audience_type` | Description |
|---|---|
| `all` | Send to all contacts |
| `tag` | Send to contacts with specific tags |
| `manual` | Specific contact IDs provided in `audience_filter` |

**Response `201`**: Broadcast object with `status: "draft"`.

---

### `GET /api/broadcasts/`

Lists all broadcasts.

**Auth required (owner).**

**Response `200`**: Array of broadcast objects.

---

### `PUT /api/broadcasts/{broadcast_id}`

Updates a draft broadcast.

**Auth required (owner).**

**Request Body**: Same fields as create (all optional).

**Response `200`**: Updated broadcast object.

---

### `POST /api/broadcasts/{broadcast_id}/send`

Sends or schedules a broadcast for delivery.

**Auth required (owner).**

**Response `200`**:
```json
{
  "status": "queued",
  "sent_count": 0
}
```

Or if sent immediately:
```json
{
  "status": "sent",
  "sent_count": 142
}
```

---

### `POST /api/broadcasts/{broadcast_id}/cancel`

Cancels a scheduled broadcast before it goes out.

**Auth required (owner).**

**Response `200`**: Updated broadcast object with `status: "cancelled"`.

---

### `GET /api/broadcasts/{broadcast_id}/stats`

Returns delivery statistics for a sent broadcast.

**Auth required (owner).**

**Response `200`**:
```json
{
  "broadcast_id": "uuid",
  "total_recipients": 142,
  "sent": 140,
  "delivered": 135,
  "failed": 2,
  "read": 98
}
```

---

### `GET /api/broadcasts/{broadcast_id}/recipients`

Lists the individual contacts targeted by a broadcast and their delivery status.

**Auth required (owner).**

**Response `200`**: Paginated list of recipient records with per-contact delivery status.

---

## 12. API Keys

Programmatic API access for server-to-server integrations. Tier: Growth+.

### `POST /api/api-keys`

Creates a new API key.

**Auth required (owner). Tier: Growth+.**

**Request Body**:
```json
{
  "name": "CRM Integration",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

**Response `201`**:
```json
{
  "id": "uuid",
  "name": "CRM Integration",
  "prefix": "abc123",
  "raw_key": "csk_abc123_xxxxxxxxxxxxxxxxxxx",
  "expires_at": "2027-01-01T00:00:00Z",
  "created_at": "2026-03-25T10:00:00Z"
}
```

> **Important**: `raw_key` is only returned once at creation. Store it securely — it cannot be retrieved again.

The key can be used as: `Authorization: Bearer csk_abc123_xxx...`

---

### `GET /api/api-keys`

Lists all API keys (without the raw key value).

**Auth required (owner).**

**Response `200`**:
```json
[
  {
    "id": "uuid",
    "name": "CRM Integration",
    "prefix": "abc123",
    "is_active": true,
    "last_used_at": "2026-03-24T15:00:00Z",
    "expires_at": "2027-01-01T00:00:00Z",
    "created_at": "2026-03-25T10:00:00Z"
  }
]
```

---

### `DELETE /api/api-keys/{key_id}`

Permanently revokes an API key.

**Auth required (owner).**

---

## 13. Billing & Subscription

### `POST /api/billing/checkout`

Creates a Razorpay checkout session to upgrade the workspace tier.

**Auth required (owner).**

**Request Body**:
```json
{
  "tier": "growth"
}
```

Valid tiers: `"starter"` | `"growth"` | `"pro"`

**Response `200`**:
```json
{
  "checkout_url": "https://rzp.io/i/abc123"
}
```

**Flow**: Redirect the user to `checkout_url`. After payment, Razorpay sends a webhook to the backend which updates the workspace tier automatically.

---

### `POST /api/billing/cancel`

Cancels the active subscription.

**Auth required (owner).**

**Response `200`**:
```json
{ "status": "cancelled" }
```

**Notes**: Cancellation takes effect at the end of the current billing cycle. The workspace reverts to `free` tier after the period ends.

---

### `GET /api/billing/status`

Returns current billing and subscription state.

**Auth required (owner).**

**Response `200`**:
```json
{
  "tier": "growth",
  "razorpay_customer_id": "cust_xxx",
  "razorpay_subscription_id": "sub_xxx"
}
```

---

## 14. Assignment Rules

Automatically route incoming escalated conversations to agents based on rules. Tier: Pro only.

### `POST /api/assignment-rules/`

Creates a new assignment rule.

**Auth required (owner). Tier: Pro.**

**Request Body**:
```json
{
  "name": "Route billing issues to finance team",
  "priority": 100,
  "conditions": {
    "escalation_reason": "billing",
    "channel_type": "webchat"
  },
  "action": "specific_agent",
  "target_agent_id": "uuid",
  "is_active": true
}
```

| `action` | Description |
|---|---|
| `round_robin` | Cycles through available agents |
| `specific_agent` | Always assigns to `target_agent_id` |
| `least_loaded` | Assigns to agent with fewest active conversations |

**Priority**: Lower number = higher priority (1 runs before 1000).

**Response `201`**: Assignment rule object.

---

### `GET /api/assignment-rules/`

Lists all assignment rules ordered by priority.

**Auth required (owner). Tier: Pro.**

**Response `200`**: Array of rule objects.

---

### `PUT /api/assignment-rules/{rule_id}`

Updates a rule.

**Auth required (owner).**

---

### `DELETE /api/assignment-rules/{rule_id}`

Deletes a rule.

**Auth required (owner).**

---

## 15. Outbound Webhooks

Register URLs to receive real-time event notifications. Tier: Growth+.

### `POST /api/webhooks/outbound`

Registers a new webhook endpoint.

**Auth required (owner). Tier: Growth+.**

**Request Body**:
```json
{
  "url": "https://yourserver.com/hooks/chaai",
  "events": [
    "conversation.created",
    "conversation.escalated",
    "conversation.resolved",
    "message.received",
    "contact.updated",
    "csat.submitted"
  ]
}
```

**Response `201`**: Webhook object including a `secret_key` used to verify HMAC signatures.

**Verification**: Each webhook request includes an `X-Signature` header — `HMAC-SHA256(secret_key, body)`.

---

### `GET /api/webhooks/outbound`

Lists registered webhooks.

**Auth required (owner).**

---

### `GET /api/webhooks/outbound/{webhook_id}/logs`

Returns webhook delivery logs (last N attempts).

**Auth required (owner).**

**Query params**: `limit`, `offset`

**Response `200`**: Array of log entries with `status_code`, `success`, `payload`, `response`, `created_at`.

---

### `GET /api/webhooks/outbound/{webhook_id}/logs/{log_id}`

Returns the full detail of a single webhook delivery log entry, including the exact payload sent and the response received.

**Auth required (owner).**

**Response `200`**: Single log entry object.

---

### `PUT /api/webhooks/outbound/{webhook_id}`

Updates a webhook (change URL, events, or active status).

**Auth required (owner).**

---

### `DELETE /api/webhooks/outbound/{webhook_id}`

Removes a webhook.

**Auth required (owner).**

---

## 16. Business Hours

Configure when your support team is available. Messages outside hours can show a custom message or pause AI responses.

### `GET /api/workspace/business-hours/`

Returns business hours configuration for all 7 days.

**Auth required (owner).**

**Response `200`**:
```json
[
  {
    "id": "uuid",
    "day_of_week": 0,
    "is_closed": false,
    "open_time": "09:00",
    "close_time": "18:00",
    "timezone": "America/New_York"
  },
  {
    "id": "uuid",
    "day_of_week": 6,
    "is_closed": true,
    "open_time": null,
    "close_time": null,
    "timezone": "America/New_York"
  }
]
```

`day_of_week`: 0 = Monday, 6 = Sunday.

---

### `PUT /api/workspace/business-hours/`

Bulk-updates all 7 days of business hours in a single call.

**Auth required (owner).**

**Request Body**: Array of day configs (same shape as single-day response):
```json
[
  { "day_of_week": 0, "is_closed": false, "open_time": "09:00", "close_time": "17:00", "timezone": "UTC" },
  { "day_of_week": 1, "is_closed": false, "open_time": "09:00", "close_time": "17:00", "timezone": "UTC" },
  { "day_of_week": 5, "is_closed": true, "open_time": null, "close_time": null, "timezone": "UTC" },
  { "day_of_week": 6, "is_closed": true, "open_time": null, "close_time": null, "timezone": "UTC" }
]
```

**Response `200`**: Full array of all 7 updated day configs.

---

### `PUT /api/workspace/outside-hours-settings`

Configures how the system behaves when a message arrives outside business hours.

**Auth required (owner).**

**Request Body**:
```json
{
  "outside_hours_message": "We're currently closed. Our hours are Mon-Fri 9am-6pm EST. We'll get back to you soon!",
  "outside_hours_behavior": "inform_and_continue"
}
```

| `outside_hours_behavior` | Description |
|---|---|
| `inform_and_continue` | Show the message, then continue with AI responses |
| `inform_and_pause` | Show the message and stop processing until open hours |

---

## 17. AI Agents

Custom AI agents with specific instructions, system prompts, and tools. Tier: Starter+.

### `POST /api/ai-agents/`

Creates a new AI agent.

**Auth required (owner). Tier: Starter+.**

**Request Body**:
```json
{
  "name": "Support Bot",
  "instructions": "You are a helpful customer support agent for Acme Corp. Be concise and friendly.",
  "system_prompt": "You specialize in product support for our B2B SaaS platform.",
  "model": "claude-sonnet-4-6",
  "temperature": 0.7,
  "tools": [],
  "guardrails": []
}
```

**Tier limits**: Free=0, Starter=1, Growth=3, Pro=5.

**Response `201`**: AI agent object.

---

### `GET /api/ai-agents/`

Lists all AI agents.

**Auth required (owner).**

---

### `GET /api/ai-agents/{agent_id}`

Gets a specific AI agent.

**Auth required (owner).**

---

### `PUT /api/ai-agents/{agent_id}`

Updates an AI agent's config.

**Auth required (owner).**

---

### `DELETE /api/ai-agents/{agent_id}`

Deletes an AI agent.

**Auth required (owner).**

---

### `POST /api/ai-agents/{agent_id}/publish`

Publishes a draft AI agent, making it live and able to handle conversations.

**Auth required (owner).**

**Response `200`**: Updated AI agent object with `is_active: true`.

**Notes**: Returns `400` if the agent config is incomplete (e.g. no instructions).

---

### Tools

#### `POST /api/ai-agents/{agent_id}/tools`

Adds a tool (function call capability) to an AI agent.

**Auth required (owner).**

**Request Body**:
```json
{
  "name": "get_order_status",
  "type": "http",
  "description": "Looks up order status from the CRM",
  "parameters": [
    {
      "name": "order_id",
      "type": "string",
      "description": "The order ID to look up",
      "required": true
    }
  ],
  "config": {
    "url": "https://api.yourcrm.com/orders/{order_id}",
    "method": "GET",
    "auth_header": "X-API-Key"
  }
}
```

**Response `201`**: Tool object.

---

#### `GET /api/ai-agents/{agent_id}/tools`

Lists all tools attached to an AI agent.

**Auth required (owner).**

**Response `200`**: Array of tool objects.

---

#### `PUT /api/ai-agents/{agent_id}/tools/{tool_id}`

Updates a tool's config, description, or parameters.

**Auth required (owner).**

**Request Body**: Same fields as create (all optional).

**Response `200`**: Updated tool object.

---

#### `DELETE /api/ai-agents/{agent_id}/tools/{tool_id}`

Removes a tool from the AI agent.

**Auth required (owner).**

**Response `204` No Content.**

---

#### `POST /api/ai-agents/{agent_id}/tools/{tool_id}/test`

Dry-runs a tool call without affecting quotas or real systems.

**Auth required (owner).**

**Request Body**:
```json
{
  "params": {
    "order_id": "ORD-12345"
  }
}
```

**Response `200`**:
```json
{
  "success": true,
  "data": { "status": "shipped", "tracking": "1Z999..." },
  "error": null,
  "latency_ms": 142,
  "status_code": 200
}
```

---

### Guardrails

Guardrails are rules that prevent the AI agent from saying or doing certain things.

#### `POST /api/ai-agents/{agent_id}/guardrails`

Adds a guardrail rule to the AI agent.

**Auth required (owner).**

**Request Body**:
```json
{
  "rule_type": "topic_block",
  "description": "Do not discuss competitor products under any circumstances"
}
```

**Response `201`**: Guardrail object with `id`, `rule_type`, `description`.

---

#### `GET /api/ai-agents/{agent_id}/guardrails`

Lists all guardrails for an AI agent.

**Auth required (owner).**

**Response `200`**: Array of guardrail objects.

---

#### `DELETE /api/ai-agents/{agent_id}/guardrails/{guardrail_id}`

Removes a guardrail.

**Auth required (owner).**

**Response `204` No Content.**

---

### Channel Assignments

#### `POST /api/ai-agents/{agent_id}/channels/{channel_id}`

Assigns an AI agent to a channel. The channel ID is in the URL path.

**Auth required (owner).**

**No request body.**

**Response `201`**: Assignment object with `ai_agent_id`, `channel_id`, `is_active`.

---

#### `DELETE /api/ai-agents/{agent_id}/channels/{channel_id}`

Removes the channel assignment from an AI agent.

**Auth required (owner).**

**Response `204` No Content.**

---

### Sandbox

#### `POST /api/ai-agents/{agent_id}/sandbox/message`

Sends a test message to the AI agent in sandbox mode. No quota is charged and no real conversation is affected.

**Auth required (owner).**

**Request Body**:
```json
{
  "message": "I want to return my order",
  "conversation_id": "sandbox-optional-custom-id"
}
```

| Field | Description |
|---|---|
| `message` | The test user message |
| `conversation_id` | Optional — reuse same session for multi-turn testing. Defaults to `sandbox-{agent_id}` |

**Response `200`**:
```json
{
  "reply": "I can help with that. Could you please provide your order number?",
  "escalated": false,
  "escalation_reason": null,
  "debug": {
    "tool_called": "get_order_status",
    "tool_params": { "order_id": "ORD-123" },
    "tool_result": { "status": "shipped" },
    "tool_success": true,
    "tool_latency_ms": 95,
    "model_used": "claude-sonnet-4-6",
    "input_tokens": 312,
    "output_tokens": 48,
    "cost_usd": 0.00041,
    "turn_count": 1,
    "escalated": false
  }
}
```

---

#### `DELETE /api/ai-agents/{agent_id}/sandbox/reset`

Clears the sandbox conversation history for this agent, starting a fresh session.

**Auth required (owner).**

**Response `204` No Content.**

---

### Analytics

#### `GET /api/ai-agents/{agent_id}/analytics`

Returns token usage and performance analytics for an AI agent.

**Auth required (owner).**

**Response `200`**:
```json
{
  "agent_id": "uuid",
  "total_conversations": 142,
  "total_input_tokens": 284000,
  "total_output_tokens": 56000,
  "total_cost_usd": 0.87,
  "avg_turns_per_conversation": 3.2,
  "escalation_rate": 0.12
}
```

---

## 18. Metrics & CSAT

### `GET /api/metrics/csat`

Returns CSAT (Customer Satisfaction) statistics for the workspace. Optionally filtered by date range.

**Auth required (owner).**

**Query params** (optional):
- `date_from` — ISO date (e.g. `2026-01-01`)
- `date_to` — ISO date

**Response `200`**:
```json
{
  "total_ratings": 87,
  "average_rating": 4.3,
  "response_rate": 0.62,
  "total_resolved_conversations": 140
}
```

| Field | Description |
|---|---|
| `total_ratings` | Number of CSAT responses submitted |
| `average_rating` | Average score (1–5 scale) |
| `response_rate` | Fraction of resolved conversations that received a CSAT rating |
| `total_resolved_conversations` | Total resolved conversations in the date range |

**Trend data** (Growth+ tier only, when date range is provided):
```json
{
  "total_ratings": 87,
  "average_rating": 4.3,
  "response_rate": 0.62,
  "total_resolved_conversations": 140,
  "trend": [
    { "date": "2026-03-20", "count": 12, "avg_rating": 4.5 },
    { "date": "2026-03-21", "count": 8, "avg_rating": 4.1 }
  ]
}
```

---

### `GET /api/metrics/workspace/{workspace_id}`

Returns detailed usage and performance metrics for the workspace.

**Auth required (owner).**

**Response `200`**: Usage stats, conversation counts by status, channel breakdown, message volume.

---

### `GET /api/metrics/system`

Returns system-wide metrics (useful for internal monitoring dashboards).

**Auth required.**

**Response `200`**: Application metrics, business metrics, DB performance metrics.

---

### `GET /api/metrics/alerts/status`

Returns current alert conditions — whether any system thresholds are exceeded.

**Auth required.**

**Response `200`**:
```json
{
  "status": "warning",
  "alerts": [
    {
      "severity": "warning",
      "message": "High number of stale conversations: 12",
      "metric": "stale_conversations",
      "value": 12,
      "threshold": 10
    }
  ],
  "alert_count": 1,
  "timestamp": 1711360000
}
```

`status` values: `ok` | `warning` | `critical`

---

## 19. WebSocket — Owner Dashboard

The owner connects to the workspace WebSocket to receive real-time events across all conversations, agents, and documents.

### Connection

```
wss://api.yourdomain.com/ws/{workspace_id}?token=<jwt_access_token>
```

- Replace `{workspace_id}` with the workspace UUID from the login response
- Pass the JWT token as a query parameter
- Reconnect with exponential backoff on disconnect

**On connect**, the server immediately sends:
```json
{
  "type": "connection_established",
  "connection_id": "conn_uuid",
  "workspace_id": "uuid",
  "user_email": "owner@company.com",
  "connected_at": "2026-03-25T10:00:00Z"
}
```

---

### Messages You Send (Client → Server)

#### Keep-Alive Ping
Send every 30 seconds to keep the connection alive:
```json
{ "type": "ping" }
```

#### Subscribe to Event Types
Filter which events you receive (optional — by default all are enabled):
```json
{
  "type": "subscribe",
  "events": ["escalation", "new_message", "agent_status_change", "document_processing"]
}
```

Available event names:
- `escalation`
- `agent_claim`
- `new_message`
- `conversation_status_change`
- `agent_status_change`
- `document_processing`
- `system_notification`

Response from server:
```json
{
  "type": "subscription_confirmed",
  "subscribed_events": ["escalation", "new_message"],
  "available_events": ["escalation", "agent_claim", "new_message", ...]
}
```

#### Request Workspace Stats
Pull current stats on demand:
```json
{ "type": "get_stats" }
```

Response:
```json
{
  "type": "workspace_stats",
  "stats": {
    "conversations": {
      "total": 1024,
      "active": 18,
      "escalated": 5,
      "agent": 3,
      "resolved": 998
    },
    "websocket_connections": 4,
    "connected_users": ["owner@company.com", "agent1@company.com"]
  }
}
```

#### Request Conversations List
Pull conversations without making a REST call:
```json
{
  "type": "get_conversations",
  "status": "escalated",
  "limit": 20,
  "offset": 0
}
```

Response:
```json
{
  "type": "conversations_list",
  "conversations": [...],
  "total_count": 5,
  "filters": { "status": "escalated" }
}
```

#### Request Agents List
```json
{ "type": "get_agents" }
```

Response:
```json
{
  "type": "agents_list",
  "agents": [...],
  "total_count": 4
}
```

---

### Events You Receive (Server → Client)

#### `escalation` — New Escalation
Fires when a conversation is flagged for human attention.

```json
{
  "type": "escalation",
  "conversation_id": "uuid",
  "escalation_reason": "keyword_match",
  "priority": "high",
  "contact_name": "John Doe",
  "channel_type": "webchat",
  "escalated_at": "2026-03-25T10:05:00Z",
  "classification": {
    "confidence": 0.95,
    "category": "billing_dispute",
    "keywords_found": ["refund", "cancel"]
  }
}
```

**UI action**: Show a toast/badge notification and update the escalated conversations list.

---

#### `agent_claim` — Agent Claimed Conversation
Fires when a human agent claims an escalated conversation.

```json
{
  "type": "agent_claim",
  "conversation_id": "uuid",
  "agent_id": "uuid",
  "agent_name": "Sarah Jones",
  "agent_email": "sarah@company.com",
  "claimed_at": "2026-03-25T10:06:00Z"
}
```

**UI action**: Move conversation from "escalated" to "agent" in the list view.

---

#### `new_message` — New Message in Any Conversation
Fires when any message arrives in the workspace.

```json
{
  "type": "new_message",
  "conversation_id": "uuid",
  "message_id": "uuid",
  "content": "I still haven't received my order",
  "role": "customer",
  "sender_name": "John Doe",
  "created_at": "2026-03-25T10:07:00Z",
  "metadata": {}
}
```

**UI action**: If the conversation is open, append the message. If not, update the last message preview in the list.

---

#### `conversation_status_change` — Status Updated
Fires when a conversation changes status (escalated, resolved, etc.).

```json
{
  "type": "conversation_status_change",
  "conversation_id": "uuid",
  "new_status": "resolved",
  "old_status": "agent",
  "changed_at": "2026-03-25T10:15:00Z"
}
```

**UI action**: Update the conversation's status badge in the list and detail view.

---

#### `agent_status_change` — Agent Availability Changed
Fires when an agent goes online/offline/busy or is activated/deactivated.

```json
{
  "type": "agent_status_change",
  "agent_id": "uuid",
  "status": "online",
  "is_active": true,
  "status_reason": "manual_update",
  "last_heartbeat_at": "2026-03-25T10:00:00Z"
}
```

**UI action**: Update the agent's status indicator in the agents list.

---

#### `document_processing` — Document Status Update
Fires at each stage of document processing after upload.

```json
{
  "type": "document_processing",
  "document_id": "uuid",
  "status": "completed",
  "progress": 100,
  "chunks_processed": 42,
  "error_message": null
}
```

**UI action**: Update the document's status in the documents list. Show a progress bar during `processing` state.

---

#### `system_notification` — System Alert
Platform-level notifications (maintenance, feature announcements, errors).

```json
{
  "type": "system_notification",
  "message": "AI service temporarily degraded. Responses may be slower.",
  "level": "warning",
  "timestamp": "2026-03-25T10:00:00Z"
}
```

**`level`**: `info` | `warning` | `error`

---

#### `error` — WebSocket Error
```json
{
  "type": "error",
  "message": "Invalid message format"
}
```

---

## 20. Tier Limits Reference

| Feature | Free | Starter | Growth | Pro |
|---|---|---|---|---|
| Monthly messages | 100 | 1,000 | 10,000 | Unlimited |
| Channels | 1 | 3 | 5 | Unlimited |
| Human agents | 0 | 2 | 5 | Unlimited |
| Documents (RAG) | 0 | 5 | 20 | Unlimited |
| Canned responses | 0 | 10 | 50 | Unlimited |
| AI agents | 0 | 1 | 3 | 5 |
| Custom AI model | No | No | Yes | Yes |
| API key access | No | No | Yes | Yes |
| Outbound webhooks | No | No | Yes | Yes |
| Assignment rules | No | No | No | Yes |

When a limit is exceeded, the API returns **`402 Payment Required`** with a message indicating which limit was hit.

---

## 21. Error Codes

All error responses follow this shape:
```json
{
  "detail": "Human-readable error message"
}
```

| HTTP Code | Meaning |
|---|---|
| `400 Bad Request` | Invalid request body, missing fields, or validation error |
| `401 Unauthorized` | Token missing, invalid, or expired |
| `402 Payment Required` | Tier limit exceeded — upgrade required |
| `403 Forbidden` | Authenticated but not permitted (e.g., accessing another workspace) |
| `404 Not Found` | Resource doesn't exist or doesn't belong to this workspace |
| `409 Conflict` | Duplicate resource (e.g., email already registered, shortcut taken) |
| `413 Payload Too Large` | File upload exceeds 10MB limit |
| `500 Internal Server Error` | Unexpected server error |
| `503 Service Unavailable` | External service (Razorpay, AI provider) unreachable |

### Common error messages

| Scenario | HTTP | Message |
|---|---|---|
| Wrong password | 401 | "Invalid credentials" |
| Expired token | 401 | "Token expired" |
| Agent limit reached | 402 | "Agent limit reached for your tier. Upgrade to add more agents." |
| Document limit reached | 402 | "Document limit reached for your tier." |
| Feature not in tier | 402 | "This feature requires Growth tier or higher." |
| Invitation expired | 400 | "Invitation token expired" |
| Channel not found | 404 | "Channel not found" |
| Conversation access denied | 403 | "You don't have access to this conversation" |
