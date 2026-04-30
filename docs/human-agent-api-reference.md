# Human Agent Platform — API Reference

> Base URL: `https://<your-domain>`  
> All endpoints require a `Bearer` JWT token in the `Authorization` header unless marked **Public**.

---

## Table of Contents

1. [Authentication Overview](#authentication-overview)
2. [Agent Lifecycle Management](#agent-lifecycle-management)
   - [Invite Agent](#1-invite-agent)
   - [Validate Invitation Token](#2-validate-invitation-token-public)
   - [Accept Invitation](#3-accept-invitation)
   - [List Agents](#4-list-agents)
   - [List Pending Invitations](#5-list-pending-invitations)
   - [Resend Invitation](#6-resend-invitation)
   - [Activate Agent](#7-activate-agent)
   - [Deactivate Agent](#8-deactivate-agent)
   - [Delete Pending Invitation](#9-delete-pending-invitation)
   - [Get Agent Statistics](#10-get-agent-statistics)
3. [Agent Presence](#agent-presence)
   - [Update My Status](#11-update-my-status)
   - [Get My Status](#12-get-my-status)
4. [Conversation Management](#conversation-management)
   - [List Conversations](#13-list-conversations)
   - [Search Conversations](#14-search-conversations)
   - [Get Conversation Detail](#15-get-conversation-detail)
   - [Get My Active Conversations](#16-get-my-active-conversations)
   - [Claim Conversation](#17-claim-conversation)
   - [Update Conversation Status](#18-update-conversation-status)
   - [Send Message](#19-send-message)
   - [Get Conversation Statistics](#20-get-conversation-statistics)
   - [Export Conversations CSV](#21-export-conversations-csv)
   - [Get CSAT Rating](#22-get-csat-rating)
5. [Internal Notes](#internal-notes)
   - [Create Note](#23-create-internal-note)
   - [List Notes](#24-list-internal-notes)
6. [AI Message Feedback](#ai-message-feedback)
   - [Submit Feedback](#25-submit-ai-message-feedback)
7. [Error Reference](#error-reference)
8. [Permission Reference](#permission-reference)
9. [WebSocket Events](#websocket-events)

---

## Authentication Overview

All agent endpoints use **JWT Bearer tokens**. The token encodes:

| Claim | Description |
|-------|-------------|
| `sub` | User ID (UUID) |
| `workspace_id` | Workspace UUID |
| `role` | `owner` or `agent` |
| `permissions` | Array of permission keys |

```http
Authorization: Bearer <jwt_token>
```

**Workspace resolution:**  
Endpoints that accept API-key auth (in addition to JWT) use the `X-API-Key` header. Agent-specific endpoints **always** require JWT.

---

## Agent Lifecycle Management

### 1. Invite Agent

Send an email invitation to a new human agent.

```
POST /api/agents/invite
```

**Auth:** JWT (workspace owner only)  
**Permission:** None required beyond ownership

**Request Body**

```json
{
  "email": "agent@example.com",
  "name": "Jane Smith"
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `email` | `string` (EmailStr) | Yes | Valid email format |
| `name` | `string` | Yes | 1–100 characters |

**Response `201 Created`**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "agent@example.com",
  "name": "Jane Smith",
  "invitation_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "invitation_expires_at": "2026-04-19T12:00:00+00:00",
  "invited_at": "2026-04-12T12:00:00+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` (UUID) | Agent record ID |
| `email` | `string` | Agent email |
| `name` | `string` | Agent display name |
| `invitation_token` | `string` | Token to include in invite link (expires in 7 days) |
| `invitation_expires_at` | `string` (ISO 8601) | Token expiry timestamp |
| `invited_at` | `string` (ISO 8601) | Invitation creation timestamp |

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Agent email already exists in workspace, or already active |
| `402 Payment Required` | Workspace tier agent limit reached |
| `422 Unprocessable Entity` | Validation error (bad email format, name too short, etc.) |
| `500 Internal Server Error` | Unexpected server error |

**Example — Invite Link Construction**

The frontend should construct the invite link as:
```
https://app.yourplatform.com/accept-invite?token=<invitation_token>
```

---

### 2. Validate Invitation Token (Public)

Check whether an invitation token is valid before asking the user to register/log in.

```
GET /api/agents/invitation/{invitation_token}
```

**Auth:** None (public endpoint)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `invitation_token` | `string` | The token from the invite link |

**Response `200 OK`**

```json
{
  "valid": true,
  "agent_email": "agent@example.com",
  "agent_name": "Jane Smith",
  "workspace_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "expires_at": "2026-04-19T12:00:00+00:00"
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Token is invalid, already used, or expired |

---

### 3. Accept Invitation

Called after the agent has registered/logged in and needs to link their account to the workspace.

```
POST /api/agents/accept
```

**Auth:** JWT (the new agent's own token)

**Request Body**

```json
{
  "invitation_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `invitation_token` | `string` | Yes | Token from the invite email |

**Response `200 OK`**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "agent@example.com",
  "name": "Jane Smith",
  "is_active": true,
  "user_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "invited_at": "2026-04-12T12:00:00+00:00",
  "accepted_at": "2026-04-12T13:05:00+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` (UUID) | Agent record ID |
| `email` | `string` | Agent email |
| `name` | `string` | Agent display name |
| `is_active` | `boolean` | Whether the agent is active |
| `user_id` | `string` (UUID) | Linked user account ID |
| `invited_at` | `string` (ISO 8601) | Invitation creation time |
| `accepted_at` | `string` (ISO 8601) \| `null` | Time invitation was accepted |

**Side Effects**
- Broadcasts a `agent.status_change` WebSocket event to all workspace connections notifying that a new agent joined.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Token expired, already used, or not found |

---

### 4. List Agents

Returns all agents in the workspace (optionally including inactive ones).

```
GET /api/agents/
```

**Auth:** JWT  
**Permission:** `team.manage`

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_inactive` | `boolean` | `false` | Include deactivated agents |

**Response `200 OK`**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "agent@example.com",
    "name": "Jane Smith",
    "is_active": true,
    "user_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "invited_at": "2026-04-12T12:00:00+00:00",
    "accepted_at": "2026-04-12T13:05:00+00:00"
  }
]
```

> Agents who have not yet accepted their invitation have `user_id: null` and `accepted_at: null`.

---

### 5. List Pending Invitations

Returns all invitations that have been sent but not yet accepted.

```
GET /api/agents/pending
```

**Auth:** JWT (workspace owner)

**Response `200 OK`**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "newagent@example.com",
    "name": "Bob Jones",
    "invitation_token": "abc123...",
    "invitation_expires_at": "2026-04-19T12:00:00+00:00",
    "invited_at": "2026-04-12T12:00:00+00:00"
  }
]
```

---

### 6. Resend Invitation

Generate a fresh token (another 7-day window) and re-send the invitation to the agent.

```
POST /api/agents/{agent_id}/resend
```

**Auth:** JWT (workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_id` | `string` (UUID) | The agent's record ID |

**Response `200 OK`** — same shape as [Invite Agent](#1-invite-agent) response, with a new `invitation_token` and `invitation_expires_at`.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Agent has already accepted invitation |

---

### 7. Activate Agent

Re-activate a previously deactivated agent. Respects tier limits.

```
POST /api/agents/{agent_id}/activate
```

**Auth:** JWT (workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_id` | `string` (UUID) | The agent's record ID |

**Response `200 OK`**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "agent@example.com",
  "name": "Jane Smith",
  "is_active": true,
  "user_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "invited_at": "2026-04-12T12:00:00+00:00",
  "accepted_at": "2026-04-12T13:05:00+00:00"
}
```

**Side Effects**
- Broadcasts `agent.status_change` WebSocket event: `is_active: true`, reason `"Activated by workspace owner"`.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Agent has never accepted invitation (`user_id` is null) |
| `402 Payment Required` | Tier agent limit reached |
| `404 Not Found` | Agent not found in workspace |

---

### 8. Deactivate Agent

Suspend an active agent. Their conversations remain but they lose login access.

```
POST /api/agents/{agent_id}/deactivate
```

**Auth:** JWT (workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_id` | `string` (UUID) | The agent's record ID |

**Response `200 OK`** — same shape as [Activate Agent](#7-activate-agent) response, with `is_active: false`.

**Side Effects**
- Broadcasts `agent.status_change` WebSocket event: `is_active: false`, reason `"Deactivated by workspace owner"`.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Agent not found in workspace |

---

### 9. Delete Pending Invitation

Hard-deletes an agent record. **Only works for agents who have NOT accepted their invitation yet.** For active agents, use [Deactivate](#8-deactivate-agent) instead.

```
DELETE /api/agents/{agent_id}
```

**Auth:** JWT (workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `agent_id` | `string` (UUID) | The agent's record ID |

**Response `200 OK`**

```json
{
  "message": "Agent invitation deleted successfully"
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Agent has already accepted invitation — use deactivate instead |
| `404 Not Found` | Agent not found in workspace |

---

### 10. Get Agent Statistics

Returns workspace-level team metrics plus per-agent performance breakdown.

```
GET /api/agents/stats
```

**Auth:** JWT (workspace owner)

**Response `200 OK`**

```json
{
  "total_agents": 5,
  "active_agents": 4,
  "inactive_agents": 1,
  "pending_invitations": 2,
  "tier_info": {
    "tier": "growth",
    "max_agents": 10,
    "agents_used": 5
  },
  "per_agent": [
    {
      "agent_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Jane Smith",
      "email": "jane@example.com",
      "status": "online",
      "conversations_active": 3,
      "conversations_resolved_30d": 47,
      "avg_csat": 4.6
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_agents` | `integer` | Total agents (active + inactive, excludes pending) |
| `active_agents` | `integer` | Currently active agents |
| `inactive_agents` | `integer` | Deactivated agents |
| `pending_invitations` | `integer` | Invitations not yet accepted |
| `tier_info` | `object` | Current tier and seat usage |
| `per_agent[].status` | `string` | `online` / `offline` / `busy` |
| `per_agent[].conversations_active` | `integer` | Conversations in `escalated` or `agent` status assigned to this agent |
| `per_agent[].conversations_resolved_30d` | `integer` | Conversations resolved by this agent in the last 30 days |
| `per_agent[].avg_csat` | `float` \| `null` | Average CSAT rating for this agent's conversations |

---

## Agent Presence

Agents should call the status endpoint on a regular heartbeat (recommended: every 30–60 seconds) so the system knows they're still available.

---

### 11. Update My Status

Set the calling agent's availability status and record a heartbeat timestamp.

```
PUT /api/agents/me/status
```

**Auth:** JWT  
**Permission:** `agent_self.presence`

**Request Body**

```json
{
  "status": "online"
}
```

| Field | Type | Allowed Values |
|-------|------|----------------|
| `status` | `string` | `online`, `offline`, `busy` |

**Response `200 OK`**

```json
{
  "agent_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "online",
  "last_heartbeat_at": "2026-04-12T14:30:00+00:00"
}
```

**Side Effects**
- Broadcasts `agent.presence` WebSocket event to workspace so dashboards update in real-time.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Caller has no active agent profile in this workspace |

---

### 12. Get My Status

Retrieve the calling agent's current status and last heartbeat.

```
GET /api/agents/me/status
```

**Auth:** JWT  
**Permission:** `agent_self.presence`

**Response `200 OK`** — same shape as [Update My Status](#11-update-my-status) response.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Caller has no agent profile in this workspace |

---

## Conversation Management

### 13. List Conversations

Paginated list of all workspace conversations with optional status filtering.

```
GET /api/conversations/
```

**Auth:** JWT

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status_filter` | `string` | `null` | Filter by status: `active`, `escalated`, `agent`, `resolved` |
| `assigned_to_me` | `boolean` | `false` | When `true`, only return conversations assigned to the calling agent |
| `limit` | `integer` | `50` | Items per page (1–100) |
| `offset` | `integer` | `0` | Pagination offset |

**Response `200 OK`**

```json
{
  "conversations": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "status": "escalated",
      "contact": {
        "id": "b3f1e2d4-...",
        "name": "John Doe",
        "external_id": "tg_123456789",
        "channel_type": "telegram",
        "metadata": {}
      },
      "assigned_agent_id": null,
      "assigned_agent_name": null,
      "escalation_reason": "User requested human support",
      "message_count": 12,
      "last_message": {
        "id": "msg-uuid",
        "content": "Can I speak to a human?",
        "role": "customer",
        "sender_name": null,
        "created_at": "2026-04-12T14:28:00+00:00",
        "metadata": null,
        "feedback": null
      },
      "created_at": "2026-04-12T10:00:00+00:00",
      "updated_at": "2026-04-12T14:28:00+00:00"
    }
  ],
  "total_count": 1,
  "has_more": false
}
```

**Conversation Status Values**

| Status | Meaning |
|--------|---------|
| `active` | Being handled by AI |
| `escalated` | Waiting to be claimed by a human agent |
| `agent` | Claimed and actively handled by a human agent |
| `resolved` | Closed |

---

### 14. Search Conversations

Full-text search across message content with optional filters.

```
GET /api/conversations/search
```

**Auth:** JWT

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | `string` | Full-text search string (searches message content via PostgreSQL `tsvector`) |
| `contact_name` | `string` | Partial match on contact name |
| `channel_type` | `string` | `telegram`, `webchat`, `whatsapp`, etc. |
| `status` | `string` | `active`, `escalated`, `agent`, `resolved` |
| `date_from` | `date` (`YYYY-MM-DD`) | Conversations created on or after this date |
| `date_to` | `date` (`YYYY-MM-DD`) | Conversations created on or before this date |
| `assigned_agent_id` | `string` (UUID) | Filter by assigned agent |
| `limit` | `integer` | Items per page (1–100, default 50) |
| `offset` | `integer` | Pagination offset (default 0) |

**Response `200 OK`**

```json
{
  "results": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "status": "resolved",
      "channel_type": "webchat",
      "contact_name": "John Doe",
      "created_at": "2026-04-10T09:00:00+00:00",
      "updated_at": "2026-04-10T11:30:00+00:00",
      "message_snippet": "...I need help with <b>billing</b> for my account..."
    }
  ],
  "total_count": 1,
  "has_more": false
}
```

> `message_snippet` is only present when `q` is provided. It is a highlighted excerpt from the matched message using PostgreSQL `ts_headline`.

---

### 15. Get Conversation Detail

Fetch a single conversation with its full message history.

```
GET /api/conversations/{conversation_id}
```

**Auth:** JWT

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | `string` (UUID) | Conversation ID |

**Response `200 OK`**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "agent",
  "contact": {
    "id": "b3f1e2d4-...",
    "name": "John Doe",
    "external_id": "tg_123456789",
    "channel_type": "telegram",
    "metadata": { "username": "@johndoe" }
  },
  "assigned_agent_id": "550e8400-e29b-41d4-a716-446655440000",
  "assigned_agent_name": "Jane Smith",
  "escalation_reason": "User requested human support",
  "messages": [
    {
      "id": "msg-uuid-1",
      "content": "Hello, I need help",
      "role": "customer",
      "sender_name": "John Doe",
      "created_at": "2026-04-12T10:00:00+00:00",
      "metadata": null,
      "feedback": null
    },
    {
      "id": "msg-uuid-2",
      "content": "Hi John! How can I help you today?",
      "role": "agent",
      "sender_name": "Jane Smith",
      "created_at": "2026-04-12T10:02:00+00:00",
      "metadata": null,
      "feedback": null
    }
  ],
  "created_at": "2026-04-12T10:00:00+00:00",
  "updated_at": "2026-04-12T10:02:00+00:00"
}
```

**Message `role` Values**

| Role | Meaning |
|------|---------|
| `customer` | Message sent by the end user |
| `assistant` | AI-generated response |
| `agent` | Human agent response |

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Conversation not found in this workspace |

---

### 16. Get My Active Conversations

Returns only conversations currently assigned to the calling agent (statuses `escalated` or `agent`).

```
GET /api/conversations/my/active
```

**Auth:** JWT  
**Permission:** `inbox.my_active`

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | `integer` | `50` | Items per page (1–100) |
| `offset` | `integer` | `0` | Pagination offset |

**Response `200 OK`** — same shape as [List Conversations](#13-list-conversations).

**Error Responses**

| Status | Condition |
|--------|-----------|
| `403 Forbidden` | Caller is not an active agent in this workspace |

---

### 17. Claim Conversation

Assign an `escalated` conversation to the calling agent, changing its status to `agent`.

```
POST /api/conversations/claim
```

**Auth:** JWT  
**Permission:** `inbox.claim`

**Request Body**

```json
{
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conversation_id` | `string` (UUID) | Yes | ID of the conversation to claim |

**Response `200 OK`**

```json
{
  "message": "Conversation claimed successfully"
}
```

**Side Effects**
- Updates conversation status from `escalated` → `agent`
- Sets `assigned_agent_id` to the calling agent's ID
- Broadcasts `conversation.claimed` WebSocket event to the workspace

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Conversation is not in `escalated` state, or already claimed |
| `403 Forbidden` | Caller is not an active agent |
| `404 Not Found` | Conversation not found |

---

### 18. Update Conversation Status

Manually transition a conversation's status (e.g., resolve it, re-escalate it).

```
POST /api/conversations/status
```

**Auth:** JWT

**Request Body**

```json
{
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "resolved",
  "note": "Issue resolved — refund processed"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conversation_id` | `string` (UUID) | Yes | Conversation to update |
| `status` | `string` | Yes | Target status: `active`, `escalated`, `agent`, `resolved` |
| `note` | `string` | No | Optional context note for the transition |

**Response `200 OK`**

```json
{
  "message": "Conversation status updated to resolved"
}
```

**Authorization Rules**

| Caller Role | Can Update |
|-------------|------------|
| Workspace owner | Any conversation |
| Active agent | Only conversations assigned to them |

**Side Effects When Resolving**
- Fires `conversation.resolved` outbound webhook
- For `webchat` conversations: triggers CSAT prompt to the customer
- Pushes status change to the customer's WebSocket connection

**Error Responses**

| Status | Condition |
|--------|-----------|
| `400 Bad Request` | Invalid status transition |
| `404 Not Found` | Conversation not found |

---

### 19. Send Message

Send a human agent message into a conversation. Delivered to the customer in real-time via WebSocket (webchat) or Telegram API.

```
POST /api/conversations/{conversation_id}/messages
```

**Auth:** JWT

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | `string` (UUID) | Conversation to post the message in |

**Request Body**

```json
{
  "content": "Hi John! I've processed your refund — it will appear within 3–5 business days."
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `content` | `string` | Yes | 1–2000 characters |

**Response `200 OK`**

```json
{
  "message": "Message sent successfully",
  "message_id": "d290f1ee-6c54-4b01-90e6-d701748f0851"
}
```

**Authorization Rules**

| Caller Role | Can Send |
|-------------|----------|
| Workspace owner | Any conversation |
| Active agent | Any conversation in this workspace (message saved with their agent identity) |
| Unauthenticated / non-agent | `403 Forbidden` |

**Side Effects**
- Broadcasts `message.new` WebSocket event to all agents watching the workspace
- For `webchat` conversations: pushes message to customer's WebSocket session
- For `telegram` conversations: delivers via Telegram Bot API

**Error Responses**

| Status | Condition |
|--------|-----------|
| `403 Forbidden` | Caller is not an active agent or owner |
| `404 Not Found` | Conversation not found |

---

### 20. Get Conversation Statistics

Summary counts for the workspace's conversation pipeline.

```
GET /api/conversations/stats/summary
```

**Auth:** JWT

**Response `200 OK`**

```json
{
  "total_conversations": 342,
  "active_conversations": 28,
  "escalated_conversations": 5,
  "agent_conversations": 8,
  "resolved_conversations": 301,
  "my_conversations": 3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_conversations` | `integer` | All conversations in workspace |
| `active_conversations` | `integer` | Currently handled by AI |
| `escalated_conversations` | `integer` | Waiting for a human to claim |
| `agent_conversations` | `integer` | Actively handled by a human agent |
| `resolved_conversations` | `integer` | Closed conversations |
| `my_conversations` | `integer` \| `null` | Conversations assigned to the calling agent (agents only) |

---

### 21. Export Conversations CSV

Stream a CSV export of all conversations matching optional filters.

```
GET /api/conversations/export
```

**Auth:** JWT  
**Permission:** `inbox.export`  
**Tier Requirement:** Growth or Pro

**Query Parameters** — same as [Search Conversations](#14-search-conversations) (`q`, `contact_name`, `channel_type`, `status`, `date_from`, `date_to`, `assigned_agent_id`)

**Response `200 OK`** — `Content-Type: text/csv`

```
conversation_id,contact_name,channel_type,status,created_at,resolved_at,message_count,escalated,assigned_agent_name,csat_rating
3fa85f64-...,John Doe,telegram,resolved,2026-04-10T09:00:00,...,15,yes,Jane Smith,5
```

**CSV Columns**

| Column | Description |
|--------|-------------|
| `conversation_id` | UUID |
| `contact_name` | Customer name |
| `channel_type` | Channel (telegram, webchat, etc.) |
| `status` | Current status |
| `created_at` | ISO 8601 |
| `resolved_at` | ISO 8601 or empty |
| `message_count` | Total messages |
| `escalated` | `yes` / `no` |
| `assigned_agent_name` | Agent name or empty |
| `csat_rating` | 1–5 or empty |

**Error Responses**

| Status | Condition |
|--------|-----------|
| `403 Forbidden` | Tier does not support CSV export |

---

### 22. Get CSAT Rating

Fetch the customer satisfaction rating submitted for a conversation.

```
GET /api/conversations/{conversation_id}/csat
```

**Auth:** JWT

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | `string` (UUID) | Conversation ID |

**Response `200 OK`** (when a rating exists)

```json
{
  "id": "csat-uuid",
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "rating": 5,
  "comment": "Jane was incredibly helpful!",
  "submitted_at": "2026-04-12T15:00:00+00:00"
}
```

**Response `200 OK`** (when no rating has been submitted)

```json
null
```

---

## Internal Notes

Internal notes are private annotations visible only to agents and workspace owners — never to the customer.

---

### 23. Create Internal Note

Add a private note to a conversation.

```
POST /api/conversations/{conversation_id}/notes
```

**Auth:** JWT (agent or workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | `string` (UUID) | Conversation to attach the note to |

**Request Body**

```json
{
  "content": "Customer is VIP — handle with priority. Account: ENT-4521."
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `content` | `string` | Yes | 1–5000 characters |

**Response `201 Created`**

```json
{
  "id": "note-uuid",
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "agent_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "Customer is VIP — handle with priority. Account: ENT-4521.",
  "created_at": "2026-04-12T14:45:00+00:00"
}
```

> If the caller is the workspace owner (not an agent), `agent_id` will be `null`.

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Conversation not found |

---

### 24. List Internal Notes

Retrieve all internal notes for a conversation in chronological order.

```
GET /api/conversations/{conversation_id}/notes
```

**Auth:** JWT (agent or workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | `string` (UUID) | Conversation ID |

**Response `200 OK`**

```json
[
  {
    "id": "note-uuid-1",
    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "agent_id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "Customer is VIP — handle with priority.",
    "created_at": "2026-04-12T14:45:00+00:00"
  },
  {
    "id": "note-uuid-2",
    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "agent_id": null,
    "content": "Owner note: escalate if unresolved by EOD.",
    "created_at": "2026-04-12T15:00:00+00:00"
  }
]
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Conversation not found |

---

## AI Message Feedback

Agents can rate AI-generated messages to improve model quality over time.

---

### 25. Submit AI Message Feedback

Submit a thumbs-up or thumbs-down rating on an AI-generated message.

```
POST /api/conversations/{conversation_id}/messages/{message_id}/feedback
```

**Auth:** JWT (agent or workspace owner)

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `conversation_id` | `string` (UUID) | Conversation containing the message |
| `message_id` | `string` (UUID) | The AI message being rated |

**Request Body**

```json
{
  "rating": "negative",
  "comment": "Answer was factually incorrect about refund policy."
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `rating` | `string` | Yes | `positive` or `negative` |
| `comment` | `string` | No | Max 1000 characters |

**Response `201 Created`**

```json
{
  "id": "feedback-uuid",
  "message_id": "msg-uuid",
  "rating": "negative",
  "comment": "Answer was factually incorrect about refund policy.",
  "created_at": "2026-04-12T14:50:00+00:00"
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Conversation or message not found |
| `409 Conflict` | Feedback already submitted for this message |

---

## Error Reference

All error responses follow a consistent envelope:

```json
{
  "detail": "Human-readable error description"
}
```

| HTTP Status | Meaning |
|-------------|---------|
| `400 Bad Request` | Invalid input, constraint violation, or invalid state transition |
| `401 Unauthorized` | Missing or invalid JWT token |
| `402 Payment Required` | Tier limit exceeded |
| `403 Forbidden` | Token valid but caller lacks permission for this operation |
| `404 Not Found` | Requested resource not found in this workspace |
| `409 Conflict` | Resource already exists (duplicate email, duplicate feedback) |
| `422 Unprocessable Entity` | Pydantic validation failure — see `detail` for field-level errors |
| `500 Internal Server Error` | Unexpected server-side failure |

---

## Permission Reference

Permissions are scoped to the JWT's `workspace_id`. The following keys are used across agent endpoints:

| Permission Key | Who Has It | Governs |
|----------------|------------|---------|
| `team.manage` | Workspace owner | `GET /api/agents/` |
| `agent_self.presence` | Active agents | `PUT/GET /api/agents/me/status` |
| `inbox.claim` | Active agents | `POST /api/conversations/claim` |
| `inbox.my_active` | Active agents | `GET /api/conversations/my/active` |
| `inbox.export` | Owner (Growth+ tier) | `GET /api/conversations/export` |

---

## WebSocket Events

The agent platform emits real-time events over the workspace WebSocket connection at:

```
ws://<your-domain>/ws/{workspace_id}
```

All events are JSON objects with a `type` field:

### Agent Events

| Event Type | Trigger | Payload |
|------------|---------|---------|
| `agent.status_change` | Agent activated / deactivated / accepts invite | `{ agent_id, is_active, status_reason }` |
| `agent.presence` | Agent updates their `online/offline/busy` status | `{ agent_id, status }` |

### Conversation Events

| Event Type | Trigger | Payload |
|------------|---------|---------|
| `conversation.claimed` | Agent claims an escalated conversation | `{ conversation_id, agent_id, agent_name }` |
| `conversation.status_change` | Conversation status updated | `{ conversation_id, old_status, new_status, agent_id }` |
| `message.new` | Any new message posted | `{ conversation_id, message_id }` |

> Customers on the webchat channel receive a **separate** customer-facing WebSocket stream. Agent events are only delivered on the internal workspace stream.
