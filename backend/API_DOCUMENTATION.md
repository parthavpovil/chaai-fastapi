# ChatSaaS Backend API Documentation

Complete API reference for all REST endpoints, WebSocket connections, and webhook integrations.

## Table of Contents

1. [Authentication](#authentication)
2. [Channel Management](#channel-management)
3. [Document Management](#document-management)
4. [Agent Management](#agent-management)
5. [Conversation Management](#conversation-management)
6. [Internal Notes](#internal-notes)
7. [AI Response Feedback](#ai-response-feedback)
8. [Canned Responses](#canned-responses)
9. [Assignment Rules](#assignment-rules)
10. [Workspace](#workspace)
11. [Outbound Webhooks](#outbound-webhooks)
12. [API Keys](#api-keys)
13. [Billing](#billing)
14. [Webhooks (Incoming)](#webhooks-incoming)
15. [WebSocket](#websocket)
16. [WebChat Public API](#webchat-public-api)
17. [Platform Administration](#platform-administration)
18. [Metrics & Monitoring](#metrics--monitoring)
19. [Contact Management](#contact-management)
20. [Outbound Webhook Delivery Logs](#outbound-webhook-delivery-logs)
21. [CSAT Ratings](#csat-ratings)
22. [Business Hours](#business-hours)
23. [Conversation Search & Export](#conversation-search--export)
24. [Flow Builder](#flow-builder)
25. [WhatsApp Templates](#whatsapp-templates)
26. [Broadcasts](#broadcasts)
27. [AI Agents](#ai-agents)

---

## Authentication

Base URL: `/api/auth`

Handles user registration, login, and identity. JWT tokens returned here are used as `Bearer` tokens on all other authenticated endpoints. Agent login uses a separate flow with an invitation token.

### POST /register

Register a new user and create workspace.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "business_name": "My Business"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "is_active": true
  },
  "workspace": {
    "id": "uuid",
    "name": "My Business",
    "slug": "my-business",
    "tier": "free"
  }
}
```

**Errors:**
- 400: Email already registered
- 500: Internal server error


### POST /login

User login with email and password.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "is_active": true
  },
  "workspace": {
    "id": "uuid",
    "name": "My Business",
    "slug": "my-business",
    "tier": "free"
  }
}
```

**Errors:**
- 401: Invalid email or password
- 401: Account is inactive

### POST /agent-login

Agent login with email and password.

**Request Body:**
```json
{
  "email": "agent@example.com",
  "password": "securepassword123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "uuid",
    "email": "agent@example.com",
    "is_active": true
  },
  "workspace": null
}
```

**Errors:**
- 401: Invalid email or password
- 401: No active agent profile found

### POST /accept-invite

Accept agent invitation and create account.

**Request Body:**
```json
{
  "token": "invitation-token-string",
  "password": "securepassword123"
}
```

**Response (200):**
```json
{
  "message": "Account created. You can now log in."
}
```

**Errors:**
- 400: Invalid invitation token
- 400: Invitation has expired
- 400: Invitation already accepted

### GET /me

Get current user information.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "is_active": true
  },
  "workspace": {
    "id": "uuid",
    "name": "My Business",
    "slug": "my-business",
    "tier": "free"
  }
}
```

### POST /refresh

Silently refresh a JWT token before it expires. Pass in a valid (non-expired) token and receive a new token with a fresh expiry. Frontend should call this proactively (~5 minutes before `exp`) to avoid mid-session logouts.

**Request Body:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors:**
- 401: Invalid or expired token

---

## Channel Management

Base URL: `/api/channels`

Manages messaging channels (Telegram, WhatsApp, Instagram, WebChat) for the workspace. Each channel links the workspace to a specific platform integration. Tier limits apply to the total number of active channels.

All endpoints require authentication via Bearer token.

### POST /

Create a new channel for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "channel_type": "telegram",
  "name": "My Telegram Bot",
  "credentials": {
    "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
  },
  "is_active": true
}
```

**Channel Types & Credentials:**

**Telegram:**
```json
{
  "channel_type": "telegram",
  "credentials": {
    "bot_token": "string"
  }
}
```

**WhatsApp:**
```json
{
  "channel_type": "whatsapp",
  "credentials": {
    "phone_number_id": "string",
    "access_token": "string"
  }
}
```

**Instagram:**
```json
{
  "channel_type": "instagram",
  "credentials": {
    "page_id": "string",
    "access_token": "string"
  }
}
```

**WebChat:**
```json
{
  "channel_type": "webchat",
  "credentials": {
    "business_name": "string",
    "primary_color": "#FF5733",
    "position": "bottom-right",
    "welcome_message": "string"
  }
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "channel_type": "telegram",
  "name": "My Telegram Bot",
  "is_active": true,
  "widget_id": "widget-id-for-webchat",
  "platform_info": {},
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 400: Channel validation failed
- 402: Tier limit exceeded

### GET /

List all channels for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
[
  {
    "id": "uuid",
    "channel_type": "telegram",
    "name": "My Telegram Bot",
    "is_active": true,
    "widget_id": null,
    "platform_info": {},
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
]
```

### GET /{channel_id}

Get channel by ID.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "channel_type": "telegram",
  "name": "My Telegram Bot",
  "is_active": true,
  "widget_id": null,
  "platform_info": {},
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 404: Channel not found

### PUT /{channel_id}

Update channel information.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "name": "Updated Channel Name",
  "is_active": false
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "channel_type": "telegram",
  "name": "Updated Channel Name",
  "is_active": false,
  "widget_id": null,
  "platform_info": {},
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### DELETE /{channel_id}

Delete a channel.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message": "Channel deleted successfully"
}
```

### POST /validate/{channel_type}

Validate channel credentials without creating a channel.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
}
```

**Response (200):**
```json
{
  "valid": true,
  "channel_type": "telegram",
  "validation_result": {}
}
```

### GET /stats/summary

Get channel statistics for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "total_channels": 3,
  "active_channels": 2,
  "inactive_channels": 1,
  "by_type": {
    "telegram": {"active": 1, "inactive": 0},
    "whatsapp": {"active": 1, "inactive": 0},
    "webchat": {"active": 0, "inactive": 1}
  },
  "tier_info": {
    "current_tier": "free",
    "channel_limit": 3,
    "channels_remaining": 0
  }
}
```

---

## Document Management

Base URL: `/api/documents`

Upload and manage knowledge-base documents used by the AI for RAG (retrieval-augmented generation). Supported formats: PDF and TXT. Documents are extracted and chunked in-memory, then stored in Cloudflare R2. The `file_path` field in responses is the public R2 URL of the stored document. Tier limits apply to total document count.

All endpoints require authentication via Bearer token.

### POST /upload

Upload and process a document for the workspace knowledge base.

**Headers:**
- `Authorization: Bearer <token>`
- `Content-Type: multipart/form-data`

**Form Data:**
- `file`: Document file (PDF or TXT, max 10MB)
- `name` *(optional)*: Custom display name for the document

**Response (200):**
```json
{
  "id": "uuid",
  "name": "my-policy.pdf",
  "file_path": "https://media.yourdomain.com/documents/workspace-uuid/uuid.pdf",
  "status": "completed",
  "chunks_count": 24,
  "error_message": null,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Notes:**
- Text extraction runs in-memory before upload — corrupt or empty files are rejected immediately with no R2 write.
- `status` will be `"processing"` briefly while embeddings are generated, then `"completed"` or `"failed"`.

**Errors:**
- 400: No file provided / unsupported file type / text extraction failed
- 402: Tier document limit exceeded
- 413: File size exceeds 10MB limit

### GET /

List documents for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `status_filter`: Filter by status (`pending` | `processing` | `completed` | `failed`)
- `limit`: Maximum number of documents (default: 50)
- `offset`: Offset for pagination (default: 0)

**Response (200):**
```json
{
  "documents": [
    {
      "id": "uuid",
      "name": "my-policy.pdf",
      "file_path": "https://media.yourdomain.com/documents/workspace-uuid/uuid.pdf",
      "status": "completed",
      "chunks_count": 24,
      "error_message": null,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total_count": 1,
  "tier_info": {
    "current_tier": "free",
    "document_limit": 10,
    "documents_remaining": 9
  }
}
```

### GET /{document_id}

Get document by ID.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "name": "my-policy.pdf",
  "file_path": "https://media.yourdomain.com/documents/workspace-uuid/uuid.pdf",
  "status": "completed",
  "chunks_count": 24,
  "error_message": null,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 404: Document not found

### DELETE /{document_id}

Delete a document, its chunks, and the corresponding R2 object.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message": "Document deleted successfully"
}
```

**Notes:**
- DB records are deleted first; R2 deletion is best-effort (failure is logged but does not cause a 500).

### POST /{document_id}/reprocess

Re-download the document from R2, re-extract text, and regenerate all embeddings. The R2 file URL is preserved (no re-upload). Can be triggered on `failed` or `completed` documents.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message": "Document reprocessing started"
}
```

**Errors:**
- 400: Document can only be reprocessed if `failed` or `completed`
- 404: Document not found

### GET /stats/summary

Get document statistics for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "total_documents": 10,
  "processing_documents": 2,
  "completed_documents": 7,
  "failed_documents": 1,
  "total_chunks": 250,
  "tier_info": {
    "current_tier": "free",
    "document_limit": 10,
    "documents_remaining": 0
  }
}
```

---

## Agent Management

Base URL: `/api/agents`

Invite and manage human support agents for the workspace. Agents are invited by email and must accept the invitation before they can log in. Owners can activate, deactivate, or remove agents. Agents can update their own availability status.

All endpoints require authentication via Bearer token.


### POST /invite

Invite an agent to the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "email": "agent@example.com",
  "name": "John Doe"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "email": "agent@example.com",
  "name": "John Doe",
  "invitation_token": "token-string",
  "invitation_expires_at": "2024-01-08T00:00:00Z",
  "invited_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 400: Agent already exists
- 402: Tier limit exceeded

### POST /accept

Accept agent invitation.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "invitation_token": "token-string"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "email": "agent@example.com",
  "name": "John Doe",
  "is_active": true,
  "user_id": "uuid",
  "invited_at": "2024-01-01T00:00:00Z",
  "accepted_at": "2024-01-02T00:00:00Z",
  "deactivated_at": null
}
```

**Errors:**
- 400: Invalid or expired invitation token

### GET /

List agents for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `include_inactive`: Include inactive agents (default: false)

**Response (200):**
```json
[
  {
    "id": "uuid",
    "email": "agent@example.com",
    "name": "John Doe",
    "is_active": true,
    "user_id": "uuid",
    "invited_at": "2024-01-01T00:00:00Z",
    "accepted_at": "2024-01-02T00:00:00Z",
    "deactivated_at": null
  }
]
```

### GET /pending

List pending agent invitations.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
[
  {
    "id": "uuid",
    "email": "agent@example.com",
    "name": "John Doe",
    "invitation_token": "token-string",
    "invitation_expires_at": "2024-01-08T00:00:00Z",
    "invited_at": "2024-01-01T00:00:00Z"
  }
]
```

### POST /{agent_id}/deactivate

Deactivate an agent.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "email": "agent@example.com",
  "name": "John Doe",
  "is_active": false,
  "user_id": "uuid",
  "invited_at": "2024-01-01T00:00:00Z",
  "accepted_at": "2024-01-02T00:00:00Z",
  "deactivated_at": "2024-01-10T00:00:00Z"
}
```

### POST /{agent_id}/activate

Activate an agent (reactivate if previously deactivated).

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "email": "agent@example.com",
  "name": "John Doe",
  "is_active": true,
  "user_id": "uuid",
  "invited_at": "2024-01-01T00:00:00Z",
  "accepted_at": "2024-01-02T00:00:00Z",
  "deactivated_at": null
}
```

**Errors:**
- 400: Cannot activate agent that hasn't accepted invitation
- 402: Tier limit exceeded

### POST /{agent_id}/resend

Resend agent invitation.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "email": "agent@example.com",
  "name": "John Doe",
  "invitation_token": "new-token-string",
  "invitation_expires_at": "2024-01-15T00:00:00Z",
  "invited_at": "2024-01-01T00:00:00Z"
}
```

### DELETE /{agent_id}

Delete an agent (only for pending invitations).

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message": "Agent invitation deleted successfully"
}
```

**Errors:**
- 400: Cannot delete agent that has accepted invitation

### GET /stats

Get agent statistics for the workspace, including per-agent performance metrics.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "total_agents": 5,
  "active_agents": 4,
  "inactive_agents": 1,
  "pending_invitations": 2,
  "tier_info": {
    "current_tier": "free",
    "agent_limit": 5,
    "agents_remaining": 0
  },
  "per_agent": [
    {
      "agent_id": "uuid",
      "name": "Alice Support",
      "email": "alice@example.com",
      "status": "online",
      "conversations_active": 3,
      "conversations_resolved_30d": 42,
      "avg_csat": 4.7
    },
    {
      "agent_id": "uuid",
      "name": "Bob Support",
      "email": "bob@example.com",
      "status": "offline",
      "conversations_active": 0,
      "conversations_resolved_30d": 18,
      "avg_csat": null
    }
  ]
}
```

**Per-agent fields:**
- `conversations_active`: Conversations currently in `escalated` or `agent` status assigned to this agent
- `conversations_resolved_30d`: Conversations resolved in the last 30 days assigned to this agent
- `avg_csat`: Average CSAT rating (1-5) from customers on conversations handled by this agent. `null` if no ratings yet.

### GET /invitation/{invitation_token}

Validate agent invitation token (public endpoint).

**Response (200):**
```json
{
  "valid": true,
  "agent_email": "agent@example.com",
  "agent_name": "John Doe",
  "workspace_id": "uuid",
  "expires_at": "2024-01-08T00:00:00Z"
}
```

**Errors:**
- 404: Invalid or expired invitation token

### PUT /me/status

Set the current agent's availability status. Updates heartbeat timestamp — agents with no heartbeat for 5+ minutes are automatically set to `offline` by a background task.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "status": "online"
}
```

- `status`: `online` | `offline` | `busy`

**Response (200):**
```json
{
  "status": "online",
  "last_heartbeat_at": "2024-01-01T12:00:00Z"
}
```

**Errors:**
- 403: Only active agents can update status
- 422: Invalid status value

### GET /me/status

Get the current agent's status and last heartbeat time.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "status": "online",
  "last_heartbeat_at": "2024-01-01T12:00:00Z"
}
```

---

## Conversation Management

Base URL: `/api/conversations`

Core conversation lifecycle management. Conversations are created automatically when a customer first messages through any channel. Agents can claim escalated conversations, update status, send messages, and view full message history. Supports search, export, and paginated listing.

All endpoints require authentication via Bearer token.

### GET /

List conversations for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `status`: Filter by status (active, escalated, agent, resolved)
- `assigned_to_me`: Show only conversations assigned to current user (agents only)
- `limit`: Maximum number of conversations (default: 50, max: 100)
- `offset`: Offset for pagination (default: 0)

**Response (200):**
```json
{
  "conversations": [
    {
      "id": "uuid",
      "status": "active",
      "contact": {
        "id": "uuid",
        "name": "Customer Name",
        "external_id": "telegram-123456",
        "channel_type": "telegram",
        "metadata": {}
      },
      "assigned_agent_id": null,
      "assigned_agent_name": null,
      "escalation_reason": null,
      "message_count": 5,
      "last_message": {
        "id": "uuid",
        "content": "Hello, I need help",
        "role": "customer",
        "sender_name": "Customer Name",
        "created_at": "2024-01-01T00:00:00Z",
        "metadata": {}
      },
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total_count": 1,
  "has_more": false
}
```

### GET /{conversation_id}

Get detailed conversation information with messages.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "status": "active",
  "contact": {
    "id": "uuid",
    "name": "Customer Name",
    "external_id": "telegram-123456",
    "channel_type": "telegram",
    "metadata": {}
  },
  "assigned_agent_id": null,
  "assigned_agent_name": null,
  "escalation_reason": null,
  "messages": [
    {
      "id": "uuid",
      "content": "Hello, I need help",
      "role": "customer",
      "sender_name": "Customer Name",
      "created_at": "2024-01-01T00:00:00Z",
      "metadata": {}
    },
    {
      "id": "uuid",
      "content": "How can I help you?",
      "role": "assistant",
      "sender_name": null,
      "created_at": "2024-01-01T00:00:01Z",
      "metadata": {"rag_used": true}
    }
  ],
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 404: Conversation not found

### POST /claim

Claim an escalated conversation (agents only).

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "conversation_id": "uuid"
}
```

**Response (200):**
```json
{
  "message": "Conversation claimed successfully"
}
```

**Errors:**
- 400: Conversation cannot be claimed
- 403: Only active agents can claim conversations

### POST /status

Update conversation status.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "conversation_id": "uuid",
  "status": "resolved",
  "note": "Issue resolved"
}
```

**Response (200):**
```json
{
  "message": "Conversation status updated to resolved"
}
```

**Errors:**
- 400: Invalid status transition
- 404: Conversation not found

### POST /{conversation_id}/messages

Send a message as an agent in a conversation.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "content": "I can help you with that"
}
```

**Response (200):**
```json
{
  "message": "Message sent successfully",
  "message_id": "uuid"
}
```

**Errors:**
- 400: Conversation not found or not assigned to agent
- 403: Only active agents can send messages

### GET /stats/summary

Get conversation statistics for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "total_conversations": 100,
  "active_conversations": 20,
  "escalated_conversations": 5,
  "agent_conversations": 10,
  "resolved_conversations": 65,
  "my_conversations": 3
}
```

### GET /my/active

Get active conversations assigned to the current agent.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `limit`: Maximum number of conversations (default: 50, max: 100)
- `offset`: Offset for pagination (default: 0)

**Response (200):**
```json
{
  "conversations": [...],
  "total_count": 3,
  "has_more": false
}
```

**Errors:**
- 403: Only active agents can access this endpoint

---

## Internal Notes

Base URL: `/api/conversations/{conversation_id}/notes`

Internal notes are visible only to agents and workspace owners — never to customers.

### POST /

Create an internal note on a conversation.

**Headers:**
- `Authorization: Bearer <token>`

**Path Parameters:**
- `conversation_id`: Conversation UUID

**Request Body:**
```json
{
  "content": "Customer seems frustrated about billing. Check account history before responding."
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "agent_id": "uuid",
  "content": "Customer seems frustrated about billing. Check account history before responding.",
  "created_at": "2024-01-01T12:00:00Z"
}
```

**Errors:**
- 404: Conversation not found

### GET /

List all internal notes for a conversation.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
[
  {
    "id": "uuid",
    "conversation_id": "uuid",
    "agent_id": "uuid",
    "content": "Note text",
    "created_at": "2024-01-01T12:00:00Z"
  }
]
```

---

## AI Response Feedback

Base URL: `/api/conversations/{conversation_id}/messages/{message_id}/feedback`

Thumbs-up / thumbs-down rating system for AI-generated responses. One feedback entry per message.

### POST /

Submit feedback on an AI message.

**Headers:**
- `Authorization: Bearer <token>`

**Path Parameters:**
- `conversation_id`: Conversation UUID
- `message_id`: Message UUID

**Request Body:**
```json
{
  "rating": "negative",
  "comment": "The AI gave incorrect pricing information."
}
```

- `rating`: `positive` | `negative`
- `comment`: Optional, max 1000 chars

**Response (200):**
```json
{
  "id": "uuid",
  "message_id": "uuid",
  "rating": "negative",
  "comment": "The AI gave incorrect pricing information.",
  "created_at": "2024-01-01T12:00:00Z"
}
```

**Errors:**
- 404: Conversation or message not found
- 409: Feedback already submitted for this message

### GET /

Get feedback for a specific message. Returns `null` if none submitted.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "id": "uuid",
  "message_id": "uuid",
  "rating": "positive",
  "comment": null,
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

## Canned Responses

Base URL: `/api/canned-responses`

Pre-written responses agents can quickly insert. Tier limits: Free=5, Starter=10, Growth=50, Pro=unlimited.

All endpoints require authentication.

### POST /

Create a canned response. Owner only.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "name": "Greeting",
  "shortcut": "/hi",
  "content": "Hello! Thank you for reaching out. How can I assist you today?"
}
```

- `shortcut`: Must be unique per workspace

**Response (200):**
```json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "name": "Greeting",
  "shortcut": "/hi",
  "content": "Hello! Thank you for reaching out. How can I assist you today?",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 402: Canned response tier limit reached
- 409: Shortcut already exists for this workspace

### GET /

List all canned responses. Accessible by agents and owners.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "Greeting",
    "shortcut": "/hi",
    "content": "Hello! Thank you for reaching out.",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### PUT /{canned_response_id}

Update a canned response. Owner only.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:** (all fields optional)
```json
{
  "name": "Updated Greeting",
  "shortcut": "/hello",
  "content": "Hi there! Welcome. How may I help you?"
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Updated Greeting",
  "shortcut": "/hello",
  "content": "Hi there! Welcome. How may I help you?",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-02T00:00:00Z"
}
```

### DELETE /{canned_response_id}

Delete a canned response. Owner only.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## Assignment Rules

Base URL: `/api/assignment-rules`

Automatic conversation routing rules. **Pro tier only.**

All endpoints require owner authentication.

### POST /

Create a routing rule.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "name": "Route billing queries to senior agent",
  "priority": 10,
  "conditions": {
    "keywords": ["refund", "billing", "invoice"],
    "channel_type": "whatsapp"
  },
  "action": "specific_agent",
  "target_agent_id": "uuid",
  "is_active": true
}
```

- `action`: `round_robin` | `specific_agent` | `least_loaded`
- `target_agent_id`: Required when `action` is `specific_agent`
- `priority`: Lower number = higher priority; evaluated in ascending order

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Route billing queries to senior agent",
  "priority": 10,
  "conditions": {"keywords": ["refund", "billing", "invoice"], "channel_type": "whatsapp"},
  "action": "specific_agent",
  "target_agent_id": "uuid",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 403: Assignment rules require Pro tier

### GET /

List all assignment rules ordered by priority.

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "Route billing queries to senior agent",
    "priority": 10,
    "action": "specific_agent",
    "is_active": true
  }
]
```

### PUT /{rule_id}

Update an assignment rule.

**Request Body:** (all fields optional)
```json
{
  "is_active": false,
  "priority": 20
}
```

### DELETE /{rule_id}

Delete an assignment rule.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## Workspace

Base URL: `/api/workspace`

Workspace-level settings, AI configuration, and dashboard overview.

All endpoints require owner authentication.

### GET /overview

Get workspace dashboard statistics.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "workspace_id": "uuid",
  "name": "My Business",
  "tier": "growth",
  "conversations_today": 12,
  "messages_this_month": 430,
  "tier_quota_remaining": 570,
  "tier_quota_total": 1000
}
```

### PUT /settings

Update workspace settings. All fields optional.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "fallback_msg": "Sorry, I couldn't understand that. A human agent will assist you shortly.",
  "alert_email": "alerts@mycompany.com",
  "agents_enabled": true,
  "escalation_keywords": ["refund", "angry", "cancel", "lawsuit"],
  "escalation_sensitivity": "medium"
}
```

- `escalation_keywords`: List of words/phrases that trigger escalation to a human agent when detected in a message. Defaults to a built-in list if not set.
- `escalation_sensitivity`: Controls how aggressively the AI escalates. One of `"low"` | `"medium"` | `"high"`. Default: `"medium"`.

**Response (200):**
```json
{
  "status": "updated"
}
```

### GET /ai-config

Get current AI provider and model configuration.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "ai_provider": "groq",
  "ai_model": "llama3-8b-8192",
  "has_api_key": true
}
```

### PUT /ai-config

Set workspace AI provider/model override. **Growth+ tier only.**

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "ai_provider": "groq",
  "ai_model": "llama3-8b-8192",
  "ai_api_key": "gsk_your_groq_api_key"
}
```

- `ai_provider`: `google` | `openai` | `groq`
- `ai_model`: Optional provider-specific model name
- `ai_api_key`: Optional API key stored server-side; never returned

**Response (200):**
```json
{
  "status": "updated",
  "ai_provider": "groq",
  "ai_model": "llama3-8b-8192"
}
```

**Errors:**
- 403: Custom AI model requires Growth or Pro tier

---

## Outbound Webhooks

Base URL: `/api/webhooks/outbound`

Register external HTTPS endpoints to receive ChatSaaS events. **Growth+ tier only.**

Outbound requests include:
- `X-ChatSaaS-Signature: sha256=<hmac-sha256>` — HMAC of the JSON body using the webhook secret
- `X-Event-Type: <event>` — event name

Webhooks are auto-disabled after 5 consecutive delivery failures.

### POST /

Register an outbound webhook.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "url": "https://your-server.com/chatsaas-events",
  "events": ["message.received", "conversation.escalated", "conversation.resolved", "conversation.created"],
  "secret": "my_hmac_secret"
}
```

**Supported events:**
- `message.received` — fired for every incoming customer message
- `conversation.created` — fired when a new conversation is started
- `conversation.escalated` — fired when a conversation is escalated to a human
- `conversation.resolved` — fired when a conversation is marked resolved

**Response (200):**
```json
{
  "id": "uuid",
  "url": "https://your-server.com/chatsaas-events",
  "events": ["message.received", "conversation.escalated"],
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 403: Outbound webhooks require Growth or Pro tier

### GET /

List all registered outbound webhooks.

**Response (200):**
```json
[
  {
    "id": "uuid",
    "url": "https://your-server.com/chatsaas-events",
    "events": ["message.received"],
    "is_active": true,
    "failure_count": 0,
    "last_triggered_at": "2024-01-01T12:00:00Z",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### PUT /{webhook_id}

Update a webhook registration.

**Request Body:** (all fields optional)
```json
{
  "is_active": false,
  "url": "https://new-endpoint.com/events",
  "events": ["conversation.resolved"]
}
```

### DELETE /{webhook_id}

Delete a webhook registration.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## API Keys

Base URL: `/api/api-keys`

Long-lived API keys for programmatic access. **Growth+ tier only.**

API keys use the prefix `csk_` and can be used as Bearer tokens on any authenticated endpoint. The raw key is returned **only once** on creation — it cannot be retrieved again.

### POST /

Create a new API key.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "name": "CI/CD Pipeline Key",
  "scopes": ["conversations:read", "conversations:write"]
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "name": "CI/CD Pipeline Key",
  "key": "csk_a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "prefix": "csk_a1b2c3d4",
  "scopes": ["conversations:read", "conversations:write"],
  "created_at": "2024-01-01T00:00:00Z"
}
```

> **Note:** The `key` field is only present in the creation response. Store it securely — it cannot be retrieved again.

**Errors:**
- 403: API keys require Growth or Pro tier

### GET /

List all API keys. The raw key is never returned; only prefix and metadata.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "CI/CD Pipeline Key",
    "prefix": "csk_a1b2c3d4",
    "scopes": ["conversations:read"],
    "last_used_at": "2024-01-01T12:00:00Z",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### DELETE /{api_key_id}

Revoke and delete an API key. Immediately invalidates all requests using this key.

**Response (200):**
```json
{
  "status": "deleted"
}
```

---

## Billing

Base URL: `/api/billing`

Stripe-powered subscription management. All endpoints require owner authentication.

### GET /status

Get current subscription and billing status.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "tier": "growth",
  "stripe_customer_id": "cus_xxxx",
  "stripe_subscription_id": "sub_xxxx",
  "subscription_status": "active"
}
```

### POST /checkout

Create a Stripe checkout session to upgrade tier.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "tier": "growth",
  "success_url": "https://yourdashboard.com/billing/success",
  "cancel_url": "https://yourdashboard.com/billing"
}
```

- `tier`: `starter` | `growth` | `pro`

**Response (200):**
```json
{
  "checkout_url": "https://checkout.stripe.com/pay/cs_xxxx"
}
```

### POST /portal

Create a Stripe customer portal session to manage subscription and invoices.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "return_url": "https://yourdashboard.com/billing"
}
```

**Response (200):**
```json
{
  "portal_url": "https://billing.stripe.com/session/xxxx"
}
```

---

## Webhooks (Incoming)

Base URL: `/webhooks`

All incoming webhook endpoints are public — they do not require authentication. They use platform-specific signature verification to authenticate the sender.

All POST routes always return HTTP 200 (even on errors) to prevent the platform from retrying deliveries.

### POST /telegram/{bot_token}

Receive message updates from Telegram.

**Path Parameters:**
- `bot_token`: Telegram bot token (used to identify the channel)

**Headers:**
- `X-Telegram-Bot-Api-Secret-Token`: Secret token set when registering the webhook with Telegram

**Request Body:** Telegram [Update](https://core.telegram.org/bots/api#update) object (JSON)

**Response (200):** `{"status": "ok"}`

### GET /whatsapp/{phone_number_id}

Meta webhook verification challenge for WhatsApp.

**Path Parameters:**
- `phone_number_id`: WhatsApp phone number ID from Meta

**Query Parameters:**
- `hub.mode`: `subscribe`
- `hub.challenge`: Challenge string from Meta
- `hub.verify_token`: Token configured in Meta for Developers

**Response (200):** The `hub.challenge` value (plain text)

### POST /whatsapp/{phone_number_id}

Receive message events from WhatsApp Business.

**Path Parameters:**
- `phone_number_id`: WhatsApp phone number ID from Meta

**Headers:**
- `X-Hub-Signature-256: sha256=<hmac>` — HMAC-SHA256 of the body using the app secret

**Request Body:** WhatsApp webhook payload (JSON)

**Response (200):** `{"status": "ok"}`

### GET /instagram/{page_id}

Meta webhook verification challenge for Instagram DMs.

**Path Parameters:**
- `page_id`: Instagram Page ID from Meta

**Query Parameters:**
- `hub.mode`: `subscribe`
- `hub.challenge`: Challenge string from Meta
- `hub.verify_token`: Token configured in Meta for Developers

**Response (200):** The `hub.challenge` value (plain text)

### POST /instagram/{page_id}

Receive DM events from Instagram.

**Path Parameters:**
- `page_id`: Instagram Page ID from Meta

**Headers:**
- `X-Hub-Signature-256: sha256=<hmac>` — HMAC-SHA256 of the body using the app secret

**Request Body:** Instagram webhook payload (JSON)

**Response (200):** `{"status": "ok"}`

### POST /stripe

Receive billing events from Stripe.

**Headers:**
- `Stripe-Signature`: Stripe webhook signature for verification

**Handled events:**
- `customer.subscription.updated` — updates workspace tier
- `customer.subscription.deleted` — downgrades workspace to `free`

**Response (200):** `{"status": "ok"}`

**Errors:**
- 400: Invalid Stripe signature

### POST /resend

Receive email event webhooks from [Resend](https://resend.com). Used for tracking email delivery status (e.g., CSAT prompt emails).

**Headers:**
- `svix-id`: Svix message ID
- `svix-timestamp`: Svix message timestamp
- `svix-signature`: Svix HMAC signature (verified against `RESEND_WEBHOOK_SECRET` if configured)

**Handled events:**
- `email.sent` — Email accepted by Resend
- `email.delivered` — Email delivered to recipient
- `email.delivery_delayed` — Delivery delayed
- `email.complained` — Marked as spam
- `email.bounced` — Hard or soft bounce
- `email.opened` — Recipient opened the email
- `email.clicked` — Recipient clicked a link

**Response (200):** `{"status": "ok"}`

**Errors:**
- 401: Missing or invalid Svix signature

---

## WebSocket

WebSocket URL: `ws://your-domain/ws/{workspace_id}?token=<jwt_token>`

Real-time bidirectional event channel for workspace agents and owners. Delivers live conversation updates, new messages, escalation alerts, and agent status changes without polling. Each workspace has a single shared room; all connected clients in that workspace receive broadcasts. Authentication uses the same JWT token as REST endpoints, passed as a query parameter.


### Connection

**URL:** `/ws/{workspace_id}`

**Query Parameters:**
- `token`: JWT authentication token (required)

**Connection Established:**
```json
{
  "type": "connection_established",
  "connection_id": "uuid",
  "workspace_id": "uuid",
  "user_email": "user@example.com"
}
```

### Client → Server Messages

**Ping:**
```json
{
  "type": "ping"
}
```

**Subscribe to Events:**
```json
{
  "type": "subscribe",
  "events": ["escalation", "new_message", "agent_claim"]
}
```

**Get Statistics:**
```json
{
  "type": "get_stats"
}
```

**Get Conversations:**
```json
{
  "type": "get_conversations",
  "status": "escalated",
  "limit": 20,
  "offset": 0
}
```

**Get Agents:**
```json
{
  "type": "get_agents"
}
```

### Server → Client Messages

**Pong:**
```json
{
  "type": "pong",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**Subscription Confirmed:**
```json
{
  "type": "subscription_confirmed",
  "subscribed_events": ["escalation", "new_message"],
  "available_events": ["escalation", "agent_claim", "new_message", "conversation_status_change", "agent_status_change", "document_processing", "system_notification"]
}
```

**Escalation Event:**
```json
{
  "type": "escalation",
  "conversation_id": "uuid",
  "escalation_reason": "customer_request",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**Agent Claim Event:**
```json
{
  "type": "agent_claim",
  "conversation_id": "uuid",
  "agent_id": "uuid",
  "agent_name": "John Doe",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**New Message Event:**
```json
{
  "type": "new_message",
  "conversation_id": "uuid",
  "message_id": "uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**Conversation Status Change:**
```json
{
  "type": "conversation_status_change",
  "conversation_id": "uuid",
  "old_status": "escalated",
  "new_status": "agent",
  "agent_id": "uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**Error:**
```json
{
  "type": "error",
  "message": "Error description"
}
```

### REST Endpoints for WebSocket Management

**GET /ws/health**

WebSocket service health check.

**Response (200):**
```json
{
  "status": "healthy",
  "websocket_stats": {
    "total_connections": 10,
    "connections_by_workspace": {},
    "timestamp": "2024-01-01T00:00:00Z"
  },
  "timestamp": "2024-01-01T00:00:00Z"
}
```

**GET /ws/connections/{workspace_id}**

Get WebSocket connections for a workspace (requires authentication).

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "workspace_id": "uuid",
  "connections": [
    {
      "connection_id": "uuid",
      "user_email": "user@example.com",
      "connected_at": "2024-01-01T00:00:00Z"
    }
  ],
  "connection_count": 1
}
```

**POST /ws/broadcast/{workspace_id}**

Broadcast message to all connections in a workspace (requires authentication).

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "type": "system_notification",
  "message": "System maintenance scheduled"
}
```

**Response (200):**
```json
{
  "workspace_id": "uuid",
  "message_sent_to": 5,
  "broadcast_successful": true
}
```

---

## WebChat Public API

Base URL: `/api/webchat`

Public endpoints consumed by the embeddable website chat widget. No authentication required — requests are identified by workspace slug or session token. Handles widget configuration, message sending, file uploads, message history retrieval, and CSAT rating submission.

### GET /config/{workspace_slug}

Get WebChat widget configuration by workspace slug.

**Path Parameters:**
- `workspace_slug`: Workspace slug (e.g., "my-business")

**Response (200):**
```json
{
  "widget_id": "widget-uuid",
  "business_name": "My Business",
  "primary_color": "#FF5733",
  "position": "bottom-right",
  "welcome_message": "Hello! How can we help you today?"
}
```

**Errors:**
- 404: Workspace not found or WebChat not configured

### POST /send

Send a text or media message through the WebChat widget. Either `message` or `media_url` must be provided. For media messages, first upload the file via `POST /upload` to get the URL, then pass it here.

**Request Body (text message):**
```json
{
  "widget_id": "widget-uuid",
  "session_token": "optional-session-token",
  "message": "Hello, I need help",
  "contact_name": "John Doe",
  "contact_email": "john@example.com",
  "contact_phone": "+919847000000",
  "external_id": "usr_123",
  "metadata": {
    "plan": "premium",
    "total_orders": 12,
    "city": "Thrissur"
  }
}
```

**Request Body (media message — after uploading via /upload):**
```json
{
  "widget_id": "widget-uuid",
  "session_token": "session-token-string",
  "media_url": "https://media.yourdomain.com/media/workspace-uuid/uuid.jpg",
  "media_mime_type": "image/jpeg",
  "media_filename": "screenshot.jpg",
  "media_size": 204800,
  "message_type": "image"
}
```

**Fields:**
- `widget_id` *(required)*: Widget ID from `GET /config/{workspace_slug}`
- `session_token` *(optional)*: Omit on first message — returned in response and must be passed on all subsequent messages
- `message` *(optional)*: Text message (1–2000 chars). Required if `media_url` is not provided.
- `media_url` *(optional)*: R2 URL from `POST /upload`. Required if `message` is not provided.
- `media_mime_type` *(optional)*: MIME type of the uploaded file
- `media_filename` *(optional)*: Original filename
- `media_size` *(optional)*: File size in bytes
- `message_type` *(optional)*: `text` | `image` | `video` | `audio` | `document`
- `contact_name`, `contact_email`, `contact_phone` *(optional)*: Visitor identity
- `external_id` *(optional)*: Your internal customer ID — use for logged-in users to maintain stable identity
- `metadata` *(optional)*: Arbitrary key-value context visible to agents

**Response (200):**
```json
{
  "success": true,
  "session_token": "session-token-string",
  "message_id": "uuid",
  "response": "How can I help you?",
  "error": null
}
```

**Response (429 - Rate Limit):**
```json
{
  "success": false,
  "session_token": "session-token-string",
  "message_id": "",
  "response": null,
  "error": "Rate limit exceeded. Please try again later."
}
```

**Errors:**
- 400: Neither `message` nor `media_url` provided
- 404: Widget not found or inactive
- 429: Rate limit exceeded (shared with `/upload`)

### POST /upload

Upload a file attachment from the widget and store it in Cloudflare R2. Returns the R2 URL to pass to `POST /send`. An active session (prior text message) is required.

**Headers:**
- `Content-Type: multipart/form-data`

**Form Data:**
- `widget_id` *(required)*: Widget ID
- `session_token` *(required)*: Active session token
- `file` *(required)*: File to upload

**Supported file types:**
| Type | MIME types | Max size |
|---|---|---|
| Image | `image/jpeg`, `image/png`, `image/webp` | 5 MB |
| Video | `video/mp4` | 16 MB |
| Audio | `audio/mpeg`, `audio/ogg`, `audio/aac` | 16 MB |
| Document | `application/pdf` | 100 MB |

**Response (200):**
```json
{
  "url": "https://media.yourdomain.com/media/workspace-uuid/uuid.jpg",
  "mime_type": "image/jpeg",
  "size": 204800,
  "filename": "screenshot.jpg",
  "message_type": "image"
}
```

**Errors:**
- 401: No active session — send a text message first to start a conversation
- 404: Widget not found or inactive
- 422: Unsupported file type or file too large
- 429: Rate limit exceeded (shared with `/send`)

### GET /messages

Get messages for a WebChat session. Media messages include `media_url` and `msg_type` fields.

**Query Parameters:**
- `widget_id`: Widget ID (required)
- `session_token`: Session token (required)
- `limit`: Maximum number of messages (default: 50, max: 100)
- `offset`: Offset for pagination (default: 0)

**Response (200):**
```json
{
  "messages": [
    {
      "id": "uuid",
      "content": "Hello, I need help",
      "sender_type": "user",
      "timestamp": "2024-01-01T00:00:00Z",
      "msg_type": "text",
      "media_url": null,
      "media_mime_type": null,
      "media_filename": null,
      "media_size": null
    },
    {
      "id": "uuid",
      "content": null,
      "sender_type": "user",
      "timestamp": "2024-01-01T00:00:05Z",
      "msg_type": "image",
      "media_url": "https://media.yourdomain.com/media/workspace-uuid/uuid.jpg",
      "media_mime_type": "image/jpeg",
      "media_filename": "screenshot.jpg",
      "media_size": 204800
    },
    {
      "id": "uuid",
      "content": "How can I help you?",
      "sender_type": "assistant",
      "timestamp": "2024-01-01T00:00:06Z",
      "msg_type": "text",
      "media_url": null,
      "media_mime_type": null,
      "media_filename": null,
      "media_size": null
    }
  ],
  "has_more": false,
  "session_token": "session-token-string"
}
```

**Errors:**
- 404: Widget not found or inactive

---

## Platform Administration

Base URL: `/api/admin`

Super-admin endpoints for managing the entire platform across all workspaces. Allows listing users and workspaces, suspending accounts, changing subscription tiers, and viewing platform-wide analytics and AI feedback statistics. Requires a super admin account — regular workspace owners cannot access these endpoints.

All endpoints require super admin authentication.

### GET /overview

Get platform overview with statistics and metrics.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "total_workspaces": 100,
  "total_users": 150,
  "active_users": 120,
  "tier_breakdown": {
    "free": 80,
    "starter": 15,
    "growth": 4,
    "pro": 1
  },
  "current_month_stats": {
    "new_workspaces": 10,
    "new_users": 15,
    "total_messages": 5000
  },
  "recent_activity": {
    "last_signup": "2024-01-01T00:00:00Z",
    "last_tier_change": "2024-01-01T00:00:00Z"
  }
}
```

**Errors:**
- 403: Super admin access required

### GET /workspaces

Get paginated list of workspaces with owner information.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `limit`: Maximum number of workspaces (default: 50, max: 100)
- `offset`: Offset for pagination (default: 0)
- `tier`: Filter by tier (free, starter, growth, pro)

**Response (200):**
```json
[
  {
    "id": "uuid",
    "name": "My Business",
    "slug": "my-business",
    "tier": "free",
    "owner_email": "user@example.com",
    "owner_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "tier_changed_at": null,
    "tier_changed_by": null
  }
]
```

### GET /users

Get paginated list of users with workspace information.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `limit`: Maximum number of users (default: 50, max: 100)
- `offset`: Offset for pagination (default: 0)
- `active_only`: Only return active users (default: false)

**Response (200):**
```json
[
  {
    "id": "uuid",
    "email": "user@example.com",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "last_login": "2024-01-01T00:00:00Z",
    "workspace": {
      "id": "uuid",
      "name": "My Business",
      "tier": "free"
    }
  }
]
```

### POST /users/suspend

Suspend a user account.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "user_id": "uuid"
}
```

**Response (200):**
```json
{
  "message": "User suspended successfully"
}
```

**Errors:**
- 400: User not found
- 403: Super admin access required

### POST /users/unsuspend

Unsuspend a user account.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "user_id": "uuid"
}
```

**Response (200):**
```json
{
  "message": "User unsuspended successfully"
}
```

### POST /workspaces/change-tier

Change workspace tier with audit logging.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "workspace_id": "uuid",
  "new_tier": "starter",
  "reason": "Customer upgrade request"
}
```

**Response (200):**
```json
{
  "message": "Workspace tier changed to starter"
}
```

**Errors:**
- 400: Invalid tier or workspace not found

### GET /tier-changes

Get tier change history with audit information.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `workspace_id`: Filter by workspace ID (optional)
- `limit`: Maximum number of records (default: 50, max: 100)

**Response (200):**
```json
[
  {
    "id": "uuid",
    "workspace_id": "uuid",
    "workspace_name": "My Business",
    "workspace_slug": "my-business",
    "from_tier": "free",
    "to_tier": "starter",
    "changed_by": "admin@example.com",
    "note": "Customer upgrade request",
    "created_at": "2024-01-01T00:00:00Z"
  }
]
```

### DELETE /workspaces/delete

Delete workspace with name confirmation for safety.

**Headers:**
- `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "workspace_id": "uuid",
  "confirmation_name": "My Business"
}
```

**Response (200):**
```json
{
  "message": "Workspace deleted successfully"
}
```

**Errors:**
- 400: Confirmation name doesn't match

### GET /analytics

Get analytics dashboard with message volume, signup trends, and escalation statistics.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message_volume": {
    "last_12_months": [
      {"month": "2024-01", "count": 1000},
      {"month": "2024-02", "count": 1200}
    ],
    "total": 15000
  },
  "signup_trends": {
    "last_12_months": [
      {"month": "2024-01", "count": 10},
      {"month": "2024-02", "count": 15}
    ],
    "total": 150
  },
  "escalation_statistics": {
    "total_escalations": 500,
    "escalation_rate": 0.033,
    "by_reason": {
      "customer_request": 300,
      "sentiment_negative": 150,
      "keyword_match": 50
    }
  }
}
```

### GET /feedback/stats

Aggregate AI response feedback (thumbs-up/down) counts across all workspaces. Can be filtered to a single workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `workspace_id`: (optional) Filter results to a specific workspace UUID

**Response (200):**
```json
{
  "feedback_stats": [
    {
      "workspace_id": "uuid",
      "positive": 142,
      "negative": 23,
      "total": 165
    },
    {
      "workspace_id": "uuid",
      "positive": 88,
      "negative": 12,
      "total": 100
    }
  ]
}
```

**Errors:**
- 403: Super admin access required

---

## Metrics & Monitoring

Base URL: `/api/metrics`

Operational health and performance metrics for the platform. Includes a public Prometheus scrape endpoint, detailed health checks, per-workspace stats, system-wide counters, alert thresholds, and a CSAT summary. Used by monitoring tools (Grafana, Prometheus) and the admin dashboard.


### GET /health/detailed

Detailed health check endpoint with comprehensive system status.

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": 1704067200,
  "health": {
    "database_connected": true,
    "stale_conversations": 5,
    "failed_documents": 2,
    "inactive_channels": 1
  },
  "performance": {
    "database": {
      "active_connections": 10,
      "idle_connections": 5
    },
    "response_time_ms": 50
  }
}
```

**Errors:**
- 503: Health check failed

### GET /system

Get comprehensive system metrics (requires authentication).

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "timestamp": 1704067200,
  "application": {
    "total_workspaces": 100,
    "total_users": 150,
    "active_users": 120
  },
  "business": {
    "total_conversations": 5000,
    "active_conversations": 200,
    "escalated_conversations": 50,
    "total_messages": 25000,
    "total_documents": 500
  },
  "performance": {
    "database": {
      "active_connections": 10,
      "idle_connections": 5
    },
    "websocket_connections": 25
  },
  "health": {
    "database_connected": true,
    "stale_conversations": 5,
    "failed_documents": 2
  }
}
```

### GET /workspace/{workspace_id}

Get metrics for a specific workspace (requires authentication).

**Headers:**
- `Authorization: Bearer <token>`

**Path Parameters:**
- `workspace_id`: Workspace ID

**Response (200):**
```json
{
  "workspace_id": "uuid",
  "conversations": {
    "total": 100,
    "active": 20,
    "escalated": 5,
    "resolved": 75
  },
  "messages": {
    "total": 500,
    "last_24h": 50
  },
  "channels": {
    "total": 3,
    "active": 2
  },
  "documents": {
    "total": 10,
    "completed": 8,
    "processing": 1,
    "failed": 1
  },
  "usage": {
    "input_tokens": 10000,
    "output_tokens": 5000,
    "tier": "free",
    "limits": {
      "channels": 3,
      "agents": 5,
      "documents": 10
    }
  }
}
```

**Errors:**
- 403: Access denied to workspace metrics

### GET /prometheus

Get metrics in Prometheus format (public endpoint).

**Response (200):**
```
# HELP chatsaas_workspaces_total Total number of workspaces
# TYPE chatsaas_workspaces_total gauge
chatsaas_workspaces_total 100

# HELP chatsaas_conversations_total Total number of conversations
# TYPE chatsaas_conversations_total gauge
chatsaas_conversations_total 5000

# HELP chatsaas_messages_total Total number of messages
# TYPE chatsaas_messages_total counter
chatsaas_messages_total 25000
```

### GET /alerts/status

Get current alert status and thresholds (requires authentication).

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "status": "ok",
  "alerts": [],
  "alert_count": 0,
  "timestamp": 1704067200
}
```

**Response (200 - With Alerts):**
```json
{
  "status": "warning",
  "alerts": [
    {
      "severity": "warning",
      "message": "High number of stale conversations: 15",
      "metric": "stale_conversations",
      "value": 15,
      "threshold": 10
    }
  ],
  "alert_count": 1,
  "timestamp": 1704067200
}
```

---

## Error Responses

All endpoints follow a consistent error response format:

**400 Bad Request:**
```json
{
  "detail": "Error description"
}
```

**401 Unauthorized:**
```json
{
  "detail": "Invalid authentication credentials"
}
```

**403 Forbidden:**
```json
{
  "detail": "Access denied"
}
```

**404 Not Found:**
```json
{
  "detail": "Resource not found"
}
```

**402 Payment Required:**
```json
{
  "detail": "Tier limit exceeded. Upgrade to continue."
}
```

**413 Request Entity Too Large:**
```json
{
  "detail": "File size exceeds limit"
}
```

**429 Too Many Requests:**
```json
{
  "detail": "Rate limit exceeded"
}
```

**500 Internal Server Error:**
```json
{
  "detail": "Internal server error"
}
```

**503 Service Unavailable:**
```json
{
  "detail": "Service temporarily unavailable"
}
```

---

## Authentication

Most endpoints require JWT authentication via Bearer token in the Authorization header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Obtain tokens via:
- `/api/auth/register` - New user registration
- `/api/auth/login` - User login
- `/api/auth/agent-login` - Agent login

Tokens contain:
- `user_id`: User UUID
- `email`: User email
- `role`: User role (owner, agent)
- `workspace_id`: Associated workspace UUID
- `exp`: Token expiration timestamp

---

## Rate Limiting

Rate limits are enforced on public endpoints:

- **WebChat /send**: 10 messages per minute per session
- **WebChat /messages**: 30 requests per minute per session

Rate limit headers:
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 5
X-RateLimit-Reset: 1704067260
```

---

## Pagination

List endpoints support pagination via query parameters:

- `limit`: Maximum number of items to return (default varies by endpoint)
- `offset`: Number of items to skip

Response includes:
- `total_count`: Total number of items
- `has_more`: Boolean indicating if more items exist

---

## Webhook Security

Webhook endpoints verify signatures from platforms:

**Telegram:** No signature verification (uses bot_token in URL)

**WhatsApp/Instagram:** Verifies `X-Hub-Signature-256` header

Verification process:
1. Extract signature from header
2. Compute HMAC-SHA256 of payload with app secret
3. Compare signatures using constant-time comparison

---

## WebSocket Authentication

WebSocket connections require JWT token in query parameter:

```
ws://your-domain/ws/{workspace_id}?token=<jwt_token>
```

Connection is rejected if:
- Token is invalid or expired
- Workspace ID doesn't match token
- User doesn't have access to workspace

---

## Tier Limits

Different tiers have different limits:

| Feature | Free | Starter | Growth | Pro |
|---------|------|---------|--------|-----|
| Channels | 3 | 10 | 25 | Unlimited |
| Agents | 5 | 15 | 50 | Unlimited |
| Documents | 10 | 50 | 200 | Unlimited |
| Messages/month | 1000 | 10000 | 50000 | Unlimited |

Exceeding limits returns 402 Payment Required error.

---

## Content Types

**Request Content Types:**
- `application/json` - Most endpoints
- `multipart/form-data` - Document upload

**Response Content Types:**
- `application/json` - Most endpoints
- `text/plain` - Prometheus metrics, webhook verification

---

## Timestamps

All timestamps are in ISO 8601 format with UTC timezone:

```
2024-01-01T00:00:00Z
```

---

## UUIDs

All resource IDs are UUIDs in string format:

```
"550e8400-e29b-41d4-a716-446655440000"
```

---

## Status Codes

- `200 OK` - Successful request
- `400 Bad Request` - Invalid request parameters
- `401 Unauthorized` - Missing or invalid authentication
- `402 Payment Required` - Tier limit exceeded
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `413 Request Entity Too Large` - File size exceeded
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Service temporarily unavailable

---

## Contact Management

Base URL: `/api/contacts`

**Auth:** `Authorization: Bearer <token>` (workspace owner or agent)

Provides full CRUD for customer contacts, including search, tagging, blocking, and GDPR-compliant deletion. `custom_fields` requires Growth+ tier.

### GET /

List contacts with optional search and filters.

**Query Parameters:**

| Param | Type | Description |
|---|---|---|
| `q` | string | ILIKE search across name, email, phone |
| `tag` | string | Filter contacts that have this tag |
| `is_blocked` | boolean | Filter by blocked status |
| `limit` | int | Max results (1–100, default 50) |
| `offset` | int | Pagination offset |

**Response (200):**
```json
{
  "contacts": [
    {
      "id": "uuid",
      "external_id": "platform-specific-id",
      "name": "Jane Doe",
      "email": "jane@example.com",
      "phone": "+1234567890",
      "tags": ["vip", "billing"],
      "custom_fields": {"crm_id": "SF-001"},
      "source": "whatsapp",
      "is_blocked": false,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total_count": 42,
  "has_more": false
}
```

### GET /{contact_id}

Get contact detail with last 10 conversations.

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Jane Doe",
  "email": "jane@example.com",
  "phone": "+1234567890",
  "tags": ["vip"],
  "custom_fields": {},
  "source": "telegram",
  "is_blocked": false,
  "created_at": "2024-01-01T00:00:00Z",
  "recent_conversations": [
    {
      "id": "uuid",
      "status": "resolved",
      "channel_type": "telegram",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T01:00:00Z"
    }
  ]
}
```

### PATCH /{contact_id}

Update contact fields. `custom_fields` requires Growth+ tier.

**Request Body (all fields optional):**
```json
{
  "name": "Jane Smith",
  "email": "jane.smith@example.com",
  "phone": "+1987654321",
  "tags": ["vip", "priority"],
  "custom_fields": {"crm_id": "SF-002", "segment": "enterprise"}
}
```

**Response (200):** Updated contact object.

**Errors:**
- 403: `custom_fields` update attempted on free/starter tier

### POST /{contact_id}/block

Block a contact. Blocked contacts receive an auto-reply and are not processed through the AI pipeline. No usage is counted.

**Response (200):**
```json
{"message": "Contact blocked", "contact_id": "uuid"}
```

### POST /{contact_id}/unblock

Unblock a previously blocked contact.

**Response (200):**
```json
{"message": "Contact unblocked", "contact_id": "uuid"}
```

### DELETE /{contact_id}

Permanently delete a contact and all their data (conversations, messages). Use for GDPR compliance.

**Response (204):** No content.

**Outbound Webhook Event:** `contact.updated` is fired after a successful PATCH.

---

## Outbound Webhook Delivery Logs

Base URL: `/api/webhooks/outbound/{webhook_id}/logs`

**Auth:** `Authorization: Bearer <token>` | **Tier:** Growth+

Every delivery attempt to a registered outbound webhook URL is logged for 30 days. Use these logs to debug integration issues.

### GET /{webhook_id}/logs

List delivery logs for a webhook (last 30 days, newest first).

**Query Parameters:**

| Param | Type | Description |
|---|---|---|
| `success` | boolean | Filter by `true` (delivered) or `false` (failed) |
| `limit` | int | Max results (1–200, default 50) |
| `offset` | int | Pagination offset |

**Response (200):**
```json
{
  "logs": [
    {
      "id": "uuid",
      "event_type": "conversation.resolved",
      "payload": {"workspace_id": "uuid", "conversation_id": "uuid"},
      "response_status_code": 200,
      "response_body": "OK",
      "duration_ms": 143,
      "is_success": true,
      "delivered_at": "2024-01-01T12:00:00Z"
    }
  ],
  "total_count": 5,
  "has_more": false
}
```

### GET /{webhook_id}/logs/{log_id}

Get a single delivery log entry (includes full payload and response body).

**Response (200):** Single log object (same schema as above).

**Notes:**
- `response_status_code` is `null` on network-level failures (DNS error, timeout, connection refused)
- `response_body` is truncated to 2000 characters
- A webhook is automatically disabled after 5 consecutive failures (`is_active` → `false`)

**Supported outbound event types:**

| Event | Fired when |
|---|---|
| `conversation.created` | New conversation starts |
| `conversation.escalated` | Conversation escalated to human |
| `conversation.resolved` | Conversation marked resolved |
| `message.received` | Customer message arrives |
| `contact.updated` | Contact fields updated via API |
| `csat.submitted` | Customer submits a CSAT rating |

---

## CSAT Ratings

Customer satisfaction ratings collected after conversations are resolved.

### Public Endpoints (no auth required)

#### GET /api/webchat/csat/{token}

Validate a CSAT token before showing the rating form.

**Response (200):**
```json
{
  "valid": true,
  "conversation_id": "uuid",
  "workspace_id": "uuid"
}
```

Returns `{"valid": false}` if the token is expired (72h TTL) or invalid.

#### POST /api/webchat/csat

Submit a CSAT rating for a resolved conversation.

**Request Body:**
```json
{
  "token": "<csat-jwt-token>",
  "rating": 5,
  "comment": "Very helpful, resolved my issue quickly!"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `token` | string | Yes | JWT token from `csat_prompt` WebSocket event |
| `rating` | int | Yes | 1 (worst) – 5 (best) |
| `comment` | string | No | Max 1000 chars |

**Response (200):**
```json
{"success": true, "message": "Thank you for your feedback!"}
```

**Errors:**
- 400: Invalid or expired token
- 400: Conversation not in `resolved` status
- 409: Rating already submitted for this conversation

### Authenticated Endpoints

#### GET /api/conversations/{conversation_id}/csat

**Auth:** `Authorization: Bearer <token>`

Get the CSAT rating for a conversation, if one has been submitted.

**Response (200):**
```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "rating": 4,
  "comment": "Good support",
  "submitted_at": "2024-01-01T13:00:00Z"
}
```

Returns `null` if no rating has been submitted yet.

#### GET /api/metrics/csat

**Auth:** `Authorization: Bearer <token>`

Workspace CSAT summary. Date-range trend data requires Growth+ tier.

**Query Parameters:**

| Param | Type | Description |
|---|---|---|
| `date_from` | date | Filter start date (YYYY-MM-DD) |
| `date_to` | date | Filter end date (YYYY-MM-DD) |

**Response (200):**
```json
{
  "total_ratings": 38,
  "average_rating": 4.21,
  "response_rate": 0.76,
  "total_resolved_conversations": 50,
  "trend": [
    {"date": "2024-01-01", "count": 5, "avg_rating": 4.4},
    {"date": "2024-01-02", "count": 8, "avg_rating": 4.1}
  ]
}
```

`trend` is only included when `date_from`/`date_to` are provided and the workspace is on Growth+ tier.

**How CSAT works:**
1. A conversation is marked `resolved` (via `POST /api/conversations/status`)
2. If the channel is `webchat`, a `csat_prompt` WebSocket event is sent to the customer's session containing a signed JWT token
3. The customer submits a rating via `POST /api/webchat/csat`
4. A `csat.submitted` outbound webhook event fires

---

## Business Hours

Base URL: `/api/workspace/business-hours`

**Auth:** `Authorization: Bearer <token>` (workspace owner)

Configure operating hours so customers receive an auto-reply when messaging outside those hours.

### GET /

Get the configured schedule for all 7 days.

**Response (200):**
```json
[
  {
    "day_of_week": 0,
    "is_closed": false,
    "open_time": "09:00",
    "close_time": "17:00",
    "timezone": "America/New_York"
  },
  {
    "day_of_week": 6,
    "is_closed": true,
    "open_time": null,
    "close_time": null,
    "timezone": "America/New_York"
  }
]
```

`day_of_week`: 0 = Monday … 6 = Sunday

Returns an empty array if no hours have been configured (workspace is treated as always open).

### PUT /

Set operating hours. Pass 1–7 day configs (you don't need to include all 7 at once; unconfigured days are treated as open).

**Request Body:**
```json
[
  {
    "day_of_week": 0,
    "is_closed": false,
    "open_time": "09:00",
    "close_time": "18:00",
    "timezone": "Europe/London"
  },
  {
    "day_of_week": 5,
    "is_closed": true,
    "open_time": null,
    "close_time": null,
    "timezone": "Europe/London"
  },
  {
    "day_of_week": 6,
    "is_closed": true,
    "open_time": null,
    "close_time": null,
    "timezone": "Europe/London"
  }
]
```

`timezone` must be a valid IANA timezone name (e.g. `"UTC"`, `"America/New_York"`, `"Asia/Kolkata"`).

**Response (200):** Updated list of configured days (same schema as GET).

**Errors:**
- 400: Duplicate `day_of_week` values in request
- 400: Invalid time format (expected `HH:MM`)
- 400: More than 7 entries

### PUT /outside-hours-settings

Configure the auto-reply message and behavior when a message arrives outside hours.

**Request Body (all fields optional):**
```json
{
  "outside_hours_message": "We're closed right now. Our hours are Mon–Fri 9am–6pm EST. We'll respond on the next business day.",
  "outside_hours_behavior": "inform_and_pause"
}
```

| `outside_hours_behavior` | Effect |
|---|---|
| `inform_and_continue` | Sends the outside-hours message, then the AI also responds. Default. |
| `inform_and_pause` | Sends the outside-hours message only; conversation is set to `paused` status and no AI response is generated. |

**Response (200):**
```json
{
  "outside_hours_message": "We're closed right now...",
  "outside_hours_behavior": "inform_and_pause"
}
```

**How business hours work:**
- When a message arrives, the pipeline checks the current time against the workspace schedule (using the configured IANA timezone).
- If no hours are configured, all messages are processed normally (always open).
- The `paused` conversation status means no AI will respond until an agent or the workspace owner manually changes the status back to `active`.

---

## Conversation Search & Export

Base URL: `/api/conversations`

**Auth:** `Authorization: Bearer <token>`

Full-text search across message content using PostgreSQL `tsvector`, with filters for status, channel, date range, and assigned agent. Export returns a CSV download of matching conversations for reporting or compliance purposes.


### GET /search

Full-text search across conversation message content with optional filters.

**Query Parameters:**

| Param | Type | Description |
|---|---|---|
| `q` | string | Full-text search across message content (PostgreSQL `tsvector`) |
| `contact_name` | string | Filter by contact name (partial match) |
| `channel_type` | string | Filter by channel: `telegram`, `whatsapp`, `instagram`, `webchat` |
| `status` | string | Filter by status: `ai`, `escalated`, `agent`, `resolved`, `paused` |
| `date_from` | date | Filter conversations created on or after (YYYY-MM-DD) |
| `date_to` | date | Filter conversations created on or before (YYYY-MM-DD) |
| `assigned_agent_id` | string | Filter by assigned agent UUID |
| `limit` | int | Max results (1–100, default 50) |
| `offset` | int | Pagination offset |

**Response (200):**
```json
{
  "results": [
    {
      "id": "uuid",
      "status": "resolved",
      "channel_type": "whatsapp",
      "contact_name": "Jane Doe",
      "created_at": "2024-01-01T10:00:00Z",
      "updated_at": "2024-01-01T11:30:00Z",
      "message_snippet": "...I need help with my <b>billing</b> invoice from last month..."
    }
  ],
  "total_count": 3,
  "has_more": false
}
```

`message_snippet` contains a highlighted excerpt showing where the search query matched (HTML `<b>` tags from PostgreSQL `ts_headline`). `null` when `q` is not provided.

### GET /export

**Tier:** Growth+

Export conversations as a streamed CSV file. Accepts the same filters as `/search`.

**Query Parameters:** Same as `/search` (plus all filters above).

**Response:** `text/csv` stream with `Content-Disposition: attachment; filename=conversations.csv`

**CSV columns:**

| Column | Description |
|---|---|
| `conversation_id` | Conversation UUID |
| `contact_name` | Customer display name |
| `channel_type` | Channel the conversation came from |
| `status` | Current conversation status |
| `created_at` | ISO 8601 timestamp |
| `resolved_at` | ISO 8601 timestamp (empty if not resolved) |
| `message_count` | Total messages in conversation |
| `escalated` | `yes` if conversation was escalated, else `no` |
| `assigned_agent_name` | Agent name if assigned |
| `csat_rating` | Rating 1–5 if customer submitted CSAT (empty otherwise) |

**Errors:**
- 403: Export requires Growth or Pro tier

---

---

## Flow Builder

Base URL: `/api/flows`

Interactive message flow automation for WhatsApp. Flows are multi-step sequences triggered by keywords or manually. When a conversation enters a flow, all incoming messages are handled by the flow engine instead of the AI — until the flow completes or hands off.

**Flow step types:** `buttons`, `list`, `free_text`, `condition`, `handoff`, `end`

All endpoints require `Authorization: Bearer <token>`.

---

### POST /api/flows

Create a new flow.

**Request Body:**
```json
{
  "name": "Appointment Booking",
  "trigger_type": "keyword",
  "trigger_keywords": ["book", "appointment", "schedule"],
  "is_active": true,
  "steps": {
    "start": "ask_service",
    "steps": [
      {
        "id": "ask_service",
        "type": "buttons",
        "text": "What would you like to book?",
        "buttons": [
          { "id": "haircut", "title": "Haircut" },
          { "id": "massage", "title": "Massage" }
        ],
        "transitions": {
          "haircut": "ask_time",
          "massage": "ask_time"
        }
      },
      {
        "id": "ask_time",
        "type": "free_text",
        "text": "What date and time works for you?",
        "saves_as": "preferred_time",
        "next": "confirm"
      },
      {
        "id": "confirm",
        "type": "free_text",
        "text": "Got it! We'll confirm your booking shortly.",
        "next": "end"
      }
    ]
  }
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "name": "Appointment Booking",
  "trigger_type": "keyword",
  "trigger_keywords": ["book", "appointment", "schedule"],
  "is_active": true,
  "steps": { ... },
  "created_at": "2026-03-23T00:00:00Z",
  "updated_at": "2026-03-23T00:00:00Z"
}
```

---

### GET /api/flows

List all flows for the workspace, ordered by creation date descending.

**Response (200):** Array of flow objects.

---

### GET /api/flows/{flow_id}

Get a single flow including all steps.

**Errors:**
- 404: Flow not found

---

### PUT /api/flows/{flow_id}

Update a flow. All fields are optional.

**Request Body:**
```json
{
  "name": "Updated Name",
  "is_active": false,
  "trigger_keywords": ["hi", "hello"],
  "steps": { ... }
}
```

**Errors:**
- 404: Flow not found

---

### DELETE /api/flows/{flow_id}

Delete a flow permanently.

**Response (204):** No content.

**Errors:**
- 404: Flow not found

---

### POST /api/flows/{flow_id}/duplicate

Clone a flow. The copy starts as inactive with the name `"<original> (copy)"`.

**Response (201):** New flow object.

---

### GET /api/flows/{flow_id}/stats

Completion and drop-off statistics for a flow.

**Response (200):**
```json
{
  "flow_id": "uuid",
  "total_started": 142,
  "completed": 98,
  "abandoned": 12,
  "completion_rate": 69.0
}
```

---

## WhatsApp Templates

Base URL: `/api/templates`

Manage WhatsApp message templates. Templates must be submitted to and approved by Meta before they can be used in broadcasts or re-engagement messages. Only `draft` and `rejected` templates can be edited or submitted.

**Template statuses:** `draft` → `pending` (after submit) → `approved` or `rejected`

All endpoints require `Authorization: Bearer <token>`.

---

### POST /api/templates

Create a new template (starts in `draft` status).

**Request Body:**
```json
{
  "name": "order_confirmation",
  "category": "UTILITY",
  "language": "en",
  "header_type": "text",
  "header_content": "Order Confirmed",
  "body": "Hi {{1}}, your order #{{2}} has been confirmed. Expected delivery: {{3}}.",
  "footer": "Reply STOP to opt out",
  "buttons": null
}
```

**Fields:**
| Field | Required | Description |
|---|---|---|
| `name` | Yes | Lowercase underscore only (e.g. `order_confirmation`) |
| `category` | Yes | `MARKETING`, `UTILITY`, or `AUTHENTICATION` |
| `language` | Yes | Language code: `en`, `hi`, `ml`, `ta`, etc. |
| `header_type` | No | `none`, `text`, `image`, `video`, `document` |
| `header_content` | No | Text content if `header_type` is `text` |
| `body` | Yes | Template body. Use `{{1}}`, `{{2}}` for variables |
| `footer` | No | Footer text |
| `buttons` | No | Array of button objects |

**Response (201):** Template object.

---

### GET /api/templates

List all templates for the workspace.

**Response (200):** Array of template objects.

---

### GET /api/templates/{template_id}

Get a single template.

**Errors:**
- 404: Template not found

---

### PUT /api/templates/{template_id}

Update a template. Only allowed when status is `draft` or `rejected`. Resets status to `draft`.

**Errors:**
- 400: Template is not in an editable state
- 404: Template not found

---

### DELETE /api/templates/{template_id}

Delete a template.

**Response (204):** No content.

---

### POST /api/templates/{template_id}/submit

Submit the template to Meta for approval. Requires `waba_id` to be configured on the WhatsApp channel.

Updates status to `pending` and stores the Meta template ID. Status syncs automatically every hour via background task.

**Response (200):**
```json
{
  "status": "pending",
  "meta_template_id": "1234567890"
}
```

**Errors:**
- 400: Template is not in `draft` or `rejected` state
- 400 (from service): WhatsApp channel missing `access_token` or `waba_id`

---

### GET /api/templates/{template_id}/preview

Preview a template's rendered structure without sending it.

**Response (200):**
```json
{
  "name": "order_confirmation",
  "language": "en",
  "header": { "type": "text", "content": "Order Confirmed" },
  "body": "Hi {{1}}, your order #{{2}} has been confirmed.",
  "footer": "Reply STOP to opt out",
  "buttons": null
}
```

---

## Broadcasts

Base URL: `/api/broadcasts`

Send a WhatsApp template message to a filtered audience. Broadcasts are queued via Redis and processed by the arq worker at ~80 messages/second (WhatsApp Cloud API rate limit).

**Broadcast statuses:** `draft` → `queued` or `scheduled` → `sending` → `sent`

**Audience types:**
- `all` — every opted-in contact with a phone number
- `tag` — contacts whose tags overlap the filter
- `manual` — specific contact IDs

All endpoints require `Authorization: Bearer <token>`.

---

### POST /api/broadcasts

Create a new broadcast in `draft` status.

**Request Body:**
```json
{
  "name": "March Sale",
  "template_id": "uuid",
  "variable_mapping": {
    "{{1}}": "contact.name",
    "{{2}}": "static:40% off"
  },
  "audience_type": "tag",
  "audience_filter": { "tags": ["vip", "repeat"] },
  "scheduled_at": null
}
```

**Variable mapping sources:**
| Source | Resolves to |
|---|---|
| `contact.name` | Contact's display name |
| `contact.phone` | Contact's phone number |
| `contact.email` | Contact's email address |
| `static:<value>` | Literal string value |

**Response (201):** Broadcast object.

---

### GET /api/broadcasts

List all broadcasts for the workspace, ordered by creation date descending.

**Response (200):** Array of broadcast objects.

---

### GET /api/broadcasts/{broadcast_id}

Get a single broadcast.

**Errors:**
- 404: Broadcast not found

---

### PUT /api/broadcasts/{broadcast_id}

Update a broadcast. Only allowed when status is `draft`.

**Errors:**
- 400: Broadcast is not in draft state

---

### POST /api/broadcasts/{broadcast_id}/send

Enqueue the broadcast for sending. If `scheduled_at` is set, it will send at that time; otherwise it sends immediately.

**Response (200):**
```json
{ "status": "queued" }
```
or
```json
{ "status": "scheduled" }
```

**Errors:**
- 400: Broadcast is not in draft state

---

### POST /api/broadcasts/{broadcast_id}/cancel

Cancel a broadcast before it completes.

**Response (200):**
```json
{ "status": "cancelled" }
```

**Errors:**
- 400: Cannot cancel a broadcast that is already `sent` or `cancelled`

---

### GET /api/broadcasts/{broadcast_id}/stats

Delivery statistics for a broadcast.

**Response (200):**
```json
{
  "broadcast_id": "uuid",
  "status": "sent",
  "total": 1500,
  "sent": 1498,
  "delivered": 1350,
  "read": 890,
  "failed": 2,
  "delivery_rate": 90.1,
  "read_rate": 59.4
}
```

---

### GET /api/broadcasts/{broadcast_id}/recipients

Paginated list of per-contact delivery records.

**Query Parameters:**
- `limit` (default: 50)
- `offset` (default: 0)

**Response (200):** Array of recipient objects:
```json
[
  {
    "id": "uuid",
    "broadcast_id": "uuid",
    "contact_id": "uuid",
    "phone": "+919876543210",
    "status": "read",
    "whatsapp_message_id": "wamid.xxx",
    "sent_at": "2026-03-23T10:00:00Z",
    "delivered_at": "2026-03-23T10:00:05Z",
    "read_at": "2026-03-23T10:02:14Z",
    "failed_reason": null
  }
]
```

---

## New WebSocket Event

### message_status_update

Fired when a WhatsApp delivery receipt arrives (sent → delivered → read → failed). Use this to update tick indicators in the chat UI.

```json
{
  "type": "message_status_update",
  "message_id": "uuid",
  "whatsapp_message_id": "wamid.HBgMNjE...",
  "status": "read",
  "timestamp": "1711180800"
}
```

**Status values:** `sent` | `delivered` | `read` | `failed`

Status only moves forward — a `delivered` message will never revert to `sent`.

---

---

## AI Agents

Base URL: `/api/ai-agents`

Autonomous bots that call external tools and APIs to handle customer queries — as a third option alongside RAG and human agents. Requires **Starter tier or above**.

**Tier limits:** Free: 0 | Starter: 1 | Growth: 3 | Pro: 10

### How it fits into the pipeline

```
Incoming message
  → Flow Engine (if WhatsApp)
  → AI Agent Runner  ← new (if workspace.meta.ai_mode = "ai_agent")
  → Escalation check + RAG  ← existing fallback
```

Enable via `PUT /api/workspace/ai-pipeline` (see [Workspace](#workspace)).

---

### POST /api/ai-agents

Create a new agent (starts as draft — must be published before it handles live traffic).

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "name": "Order Support Bot",
  "system_prompt": "You are a helpful order support assistant. Use the available tools to look up order status and resolve issues.",
  "persona_name": "Aria",
  "persona_tone": "friendly",
  "first_message": "Hi! I'm Aria, your order support assistant. How can I help?",
  "escalation_trigger": "low_confidence",
  "escalation_message": "Let me connect you with a team member who can help.",
  "confidence_threshold": 0.7,
  "max_turns": 10,
  "token_budget": 8000
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "name": "Order Support Bot",
  "system_prompt": "...",
  "persona_name": "Aria",
  "persona_tone": "friendly",
  "first_message": "...",
  "escalation_trigger": "low_confidence",
  "escalation_message": "Let me connect you with a team member who can help.",
  "confidence_threshold": 0.7,
  "max_turns": 10,
  "token_budget": 8000,
  "is_active": true,
  "is_draft": true,
  "created_at": "2026-03-24T10:00:00Z",
  "updated_at": "2026-03-24T10:00:00Z",
  "tools": [],
  "guardrails": []
}
```

**Errors:** 403 (tier limit reached)

---

### GET /api/ai-agents

List all agents in the workspace.

**Headers:** `Authorization: Bearer <token>`

**Response (200):** Array of agent objects (same shape as above).

---

### GET /api/ai-agents/{agent_id}

Get full agent details including tools and guardrails.

**Headers:** `Authorization: Bearer <token>`

**Response (200):** Agent object with nested `tools` and `guardrails` arrays.

**Errors:** 404

---

### PUT /api/ai-agents/{agent_id}

Update agent settings. Only provided fields are updated.

**Headers:** `Authorization: Bearer <token>`

**Request Body:** Any subset of the create fields, e.g.:
```json
{
  "name": "Updated Bot Name",
  "max_turns": 15
}
```

**Response (200):** Updated agent object.

---

### DELETE /api/ai-agents/{agent_id}

Delete an agent and all its tools, guardrails, and channel assignments.

**Headers:** `Authorization: Bearer <token>`

**Response (204):** No content.

---

### POST /api/ai-agents/{agent_id}/publish

Validate and mark an agent live (sets `is_draft = false`). Validates: system_prompt not empty, escalation_message set, at least one active tool.

**Headers:** `Authorization: Bearer <token>`

**Response (200):** Updated agent object with `"is_draft": false`.

**Errors:** 400 with validation details if requirements not met.

---

### POST /api/ai-agents/{agent_id}/tools

Add a tool (external HTTP endpoint) the agent can call.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "name": "get_order_status",
  "display_name": "Get Order Status",
  "description": "Look up the current status of a customer order by order ID.",
  "method": "GET",
  "endpoint_url": "https://api.example.com/orders/{order_id}",
  "headers": {
    "Authorization": "Bearer sk-secret-key"
  },
  "parameters": [
    {
      "name": "order_id",
      "type": "string",
      "required": true,
      "description": "The order ID to look up"
    }
  ],
  "response_path": "order.status",
  "requires_confirmation": false,
  "is_read_only": true
}
```

**Notes:**
- `name` must be `snake_case` — the LLM uses this identifier
- `endpoint_url` supports `{variable}` substitution from tool parameters
- `headers` values are encrypted at rest
- `response_path` uses dot-notation to extract a nested field (e.g. `order.status`)

**Response (201):** Tool object.

---

### GET /api/ai-agents/{agent_id}/tools

List all tools for an agent.

**Response (200):** Array of tool objects.

---

### PUT /api/ai-agents/{agent_id}/tools/{tool_id}

Update a tool. Partial updates supported.

**Response (200):** Updated tool object.

---

### DELETE /api/ai-agents/{agent_id}/tools/{tool_id}

Delete a tool.

**Response (204):** No content.

---

### POST /api/ai-agents/{agent_id}/tools/{tool_id}/test

Dry-run a tool call without quota charges. Use this to verify your endpoint works before going live.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "params": {
    "order_id": "ORD-12345"
  }
}
```

**Response (200):**
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

### POST /api/ai-agents/{agent_id}/guardrails

Add a safety guardrail rule.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "rule_type": "forbidden_topic",
  "description": "Do not discuss competitor pricing or products"
}
```

`rule_type` values: `forbidden_topic` | `forbidden_action` | `required_escalation`

**Response (201):** Guardrail object.

---

### GET /api/ai-agents/{agent_id}/guardrails

List all guardrails for an agent.

---

### DELETE /api/ai-agents/{agent_id}/guardrails/{guardrail_id}

Delete a guardrail.

**Response (204):** No content.

---

### POST /api/ai-agents/{agent_id}/channels/{channel_id}

Assign an agent to a channel. Only one published agent can serve a channel at a time (highest priority wins).

**Headers:** `Authorization: Bearer <token>`

**Response (201):**
```json
{
  "id": "uuid",
  "agent_id": "uuid",
  "channel_id": "uuid",
  "priority": 0,
  "is_active": true,
  "created_at": "2026-03-24T10:00:00Z"
}
```

**Errors:** 404 if channel not found in workspace.

---

### DELETE /api/ai-agents/{agent_id}/channels/{channel_id}

Unassign an agent from a channel. The channel falls back to RAG mode.

**Response (204):** No content.

---

### POST /api/ai-agents/{agent_id}/sandbox/message

Test the agent interactively without affecting quotas or live conversations. The `debug` block shows exactly what happened under the hood.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "message": "Where is my order ORD-12345?",
  "conversation_id": "sandbox-session-1"
}
```

`conversation_id` is optional — omit to start a fresh session, or reuse the same value to continue a multi-turn conversation.

**Response (200):**
```json
{
  "reply": "Your order ORD-12345 is currently shipped and on its way!",
  "escalated": false,
  "escalation_reason": null,
  "debug": {
    "tool_called": "get_order_status",
    "tool_params": { "order_id": "ORD-12345" },
    "tool_result": { "status": "shipped", "tracking": "1Z999..." },
    "tool_success": true,
    "tool_latency_ms": 142,
    "model_used": "gpt-4o-mini",
    "input_tokens": 312,
    "output_tokens": 48,
    "cost_usd": 0.000075,
    "turn_count": 1,
    "escalated": false
  }
}
```

---

### DELETE /api/ai-agents/{agent_id}/sandbox/reset

Clear the sandbox session history for this agent.

**Response (204):** No content.

---

### GET /api/ai-agents/{agent_id}/analytics

Token usage and cost breakdown for the agent.

**Headers:** `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "agent_id": "uuid",
  "total_conversations": 142,
  "active_conversations": 3,
  "escalated_conversations": 18,
  "resolved_conversations": 121,
  "total_turns": 876,
  "total_input_tokens": 412000,
  "total_output_tokens": 98000,
  "total_cost_usd": 0.1234,
  "tool_calls_total": 203,
  "tool_calls_success": 198,
  "model_breakdown": [
    {
      "model": "gpt-4o-mini",
      "input_tokens": 412000,
      "output_tokens": 98000,
      "cost_usd": 0.1234
    }
  ]
}
```

---

### PUT /api/workspace/ai-pipeline

Configure the full AI pipeline for the workspace. **Requires Growth or Pro tier.**

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "ai_mode": "ai_agent",
  "ai_provider": "openai",
  "ai_model": "gpt-4o-mini",
  "ai_api_key": "sk-..."
}
```

| Field | Values | Notes |
|-------|--------|-------|
| `ai_mode` | `rag` \| `ai_agent` | Switches the whole pipeline |
| `ai_provider` | `google` \| `openai` \| `anthropic` \| `groq` | Which LLM backend |
| `ai_model` | e.g. `gpt-4o-mini`, `claude-haiku-4-5`, `gemini-2.0-flash` | Optional model override |
| `ai_api_key` | Your API key | Optional — uses platform key if omitted |

**Response (200):**
```json
{
  "status": "updated",
  "ai_mode": "ai_agent",
  "ai_provider": "openai",
  "ai_model": "gpt-4o-mini"
}
```

**Errors:** 403 (requires Growth+ tier)

---

### GET /api/workspace/ai-pipeline

Get current AI pipeline configuration.

**Response (200):**
```json
{
  "ai_mode": "rag",
  "ai_provider": "google",
  "ai_model": "gemini-2.0-flash",
  "has_api_key": false
}
```

---

## Support

For API support and questions:
- Documentation: This file
- Issues: Contact platform administrator
- Rate limit increases: Upgrade tier or contact support

---

**Last Updated:** 2026-03-24
**API Version:** 1.3
**Base URL:** `https://your-domain.com`
