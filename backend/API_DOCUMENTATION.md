# ChatSaaS Backend API Documentation

Complete API reference for all REST endpoints, WebSocket connections, and webhook integrations.

## Table of Contents

1. [Authentication](#authentication)
2. [Channel Management](#channel-management)
3. [Document Management](#document-management)
4. [Agent Management](#agent-management)
5. [Conversation Management](#conversation-management)
6. [Webhooks](#webhooks)
7. [WebSocket](#websocket)
8. [WebChat Public API](#webchat-public-api)
9. [Platform Administration](#platform-administration)
10. [Metrics & Monitoring](#metrics--monitoring)

---

## Authentication

Base URL: `/api/auth`

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

---

## Channel Management

Base URL: `/api/channels`

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

All endpoints require authentication via Bearer token.

### POST /upload

Upload and process a document for the workspace.

**Headers:**
- `Authorization: Bearer <token>`
- `Content-Type: multipart/form-data`

**Form Data:**
- `file`: Document file (PDF or TXT, max 10MB)
- `name`: Optional custom document name

**Response (200):**
```json
{
  "id": "uuid",
  "name": "document.pdf",
  "original_filename": "document.pdf",
  "file_size": 1024000,
  "content_type": "application/pdf",
  "status": "processing",
  "error_message": null,
  "chunk_count": null,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 400: No file provided / Only PDF and TXT files supported
- 402: Tier limit exceeded
- 413: File size exceeds 10MB limit

### GET /

List documents for the workspace.

**Headers:**
- `Authorization: Bearer <token>`

**Query Parameters:**
- `status_filter`: Filter by status (pending, processing, completed, failed)
- `limit`: Maximum number of documents (default: 50, max: 100)
- `offset`: Offset for pagination (default: 0)

**Response (200):**
```json
{
  "documents": [
    {
      "id": "uuid",
      "name": "document.pdf",
      "original_filename": "document.pdf",
      "file_size": 1024000,
      "content_type": "application/pdf",
      "status": "completed",
      "error_message": null,
      "chunk_count": 25,
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z"
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
  "name": "document.pdf",
  "original_filename": "document.pdf",
  "file_size": 1024000,
  "content_type": "application/pdf",
  "status": "completed",
  "error_message": null,
  "chunk_count": 25,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

**Errors:**
- 404: Document not found

### DELETE /{document_id}

Delete a document and its chunks.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message": "Document deleted successfully"
}
```

### POST /{document_id}/reprocess

Reprocess a failed document.

**Headers:**
- `Authorization: Bearer <token>`

**Response (200):**
```json
{
  "message": "Document reprocessing started"
}
```

**Errors:**
- 400: Document can only be reprocessed if failed or completed
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

Get agent statistics for the workspace.

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
  }
}
```

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

---

## Conversation Management

Base URL: `/api/conversations`

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

## Webhooks

Base URL: `/webhooks`

All webhook endpoints are public and do not require authentication. They use platform-specific signature verification.

### POST /telegram/{bot_token}

Telegram webhook endpoint.

**Path Parameters:**
- `bot_token`: Telegram bot token for channel identification

**Request Body:** Telegram Update object (JSON)

**Response (200):** `OK`

### POST /whatsapp/{phone_number_id}

WhatsApp webhook endpoint.

**Path Parameters:**
- `phone_number_id`: WhatsApp phone number ID for channel identification

**Request Body:** WhatsApp webhook payload (JSON)

**Response (200):** `OK`

### GET /whatsapp/{phone_number_id}

WhatsApp webhook verification endpoint.

**Path Parameters:**
- `phone_number_id`: WhatsApp phone number ID

**Query Parameters:**
- `hub.challenge`: Verification challenge from Meta
- `hub.verify_token`: Verification token

**Response (200):** Challenge string

### POST /instagram/{page_id}

Instagram webhook endpoint.

**Path Parameters:**
- `page_id`: Instagram page ID for channel identification

**Request Body:** Instagram webhook payload (JSON)

**Response (200):** `OK`

### GET /instagram/{page_id}

Instagram webhook verification endpoint.

**Path Parameters:**
- `page_id`: Instagram page ID

**Query Parameters:**
- `hub.challenge`: Verification challenge from Meta
- `hub.verify_token`: Verification token

**Response (200):** Challenge string

### GET /health

Webhook service health check.

**Response (200):**
```json
{
  "status": "healthy",
  "service": "webhook_processor",
  "supported_channels": ["telegram", "whatsapp", "instagram"],
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### POST /test/{channel_type}

Test webhook processing (requires authentication).

**Headers:**
- `Authorization: Bearer <token>`

**Path Parameters:**
- `channel_type`: Channel type to test (telegram, whatsapp, instagram)

**Request Body:** Test payload data (JSON)

**Response (200):**
```json
{
  "test_result": "success",
  "channel_type": "telegram",
  "processing_result": {}
}
```

---

## WebSocket

WebSocket URL: `ws://your-domain/ws/{workspace_id}?token=<jwt_token>`

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

Public endpoints for website chat widget functionality. No authentication required.


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

Send a message through WebChat widget.

**Request Body:**
```json
{
  "widget_id": "widget-uuid",
  "session_token": "optional-session-token",
  "message": "Hello, I need help",
  "contact_name": "John Doe"
}
```

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
- 404: Widget not found or inactive
- 429: Rate limit exceeded

### GET /messages

Get messages for a WebChat session.

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
      "timestamp": "2024-01-01T00:00:00Z"
    },
    {
      "id": "uuid",
      "content": "How can I help you?",
      "sender_type": "assistant",
      "timestamp": "2024-01-01T00:00:01Z"
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

---

## Metrics & Monitoring

Base URL: `/api/metrics`

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

## Support

For API support and questions:
- Documentation: This file
- Issues: Contact platform administrator
- Rate limit increases: Upgrade tier or contact support

---

**Last Updated:** 2024-01-01  
**API Version:** 1.0  
**Base URL:** `https://your-domain.com`
