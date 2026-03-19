# Workspace Architecture

## What is a Workspace?

A **workspace** is the central organizational unit in ChatSaaS. It represents a business or organization and contains all the resources, data, and configurations for that business's customer support operations.

Think of it as a **tenant** in a multi-tenant SaaS application.

## Workspace Properties

### Core Fields

```python
id: UUID                    # Unique identifier
owner_id: UUID              # User who owns this workspace
name: str                   # Business name (e.g., "Acme Corp")
slug: str                   # URL-safe identifier (e.g., "acme-corp")
tier: str                   # Subscription tier (free/starter/growth/pro)
created_at: datetime        # When workspace was created
```

### Configuration Fields

```python
fallback_msg: str           # Default message when AI can't answer
alert_email: str            # Email for alerts and notifications
agents_enabled: bool        # Whether human agents can be invited
subscription_notes: text    # Admin notes about subscription
tier_changed_at: datetime   # When tier was last changed
tier_changed_by: str        # Who changed the tier
```

## What a Workspace Contains

### 1. Channels (Communication Channels)
**Purpose**: Connect to different messaging platforms

**Types**:
- WebChat (website widget)
- Telegram
- WhatsApp
- Instagram

**Limits by Tier**:
- Free: 1 channel
- Starter: 2 channels
- Growth: 4 channels
- Pro: 4 channels

**Example**:
```
Workspace: "Acme Corp"
  └── Channels:
      ├── WebChat Widget (acme-corp.com)
      ├── Telegram Bot (@acme_support_bot)
      └── WhatsApp Business (555-0123)
```

### 2. Contacts (Customers)
**Purpose**: People who interact with your business

**Contains**:
- External contact ID (from platform)
- Display name
- Contact data (phone, email, etc.)
- Channel they came from
- Conversation history

**Example**:
```
Contact: John Doe
  - External ID: telegram_user_12345
  - Channel: Telegram
  - Conversations: 3
  - Last contact: 2 hours ago
```

### 3. Conversations
**Purpose**: Individual chat sessions with customers

**Contains**:
- Contact (who is chatting)
- Channel (where they're chatting)
- Status (active, escalated, agent, resolved)
- Messages
- Metadata

**Statuses**:
- `active`: AI is handling
- `escalated`: Needs human attention
- `agent`: Human agent is handling
- `resolved`: Conversation closed

**Example**:
```
Conversation #1234
  - Contact: John Doe
  - Channel: Telegram
  - Status: active
  - Messages: 8
  - Started: 10 minutes ago
```

### 4. Messages
**Purpose**: Individual messages in conversations

**Contains**:
- Content (text)
- Role (customer, assistant, agent)
- Metadata (tokens used, RAG info)
- Timestamps

**Example**:
```
Message #5678
  - Content: "How do I reset my password?"
  - Role: customer
  - Conversation: #1234
  - Created: 5 minutes ago
```

### 5. Agents (Human Support Staff)
**Purpose**: Human team members who handle escalated conversations

**Contains**:
- User account (email, password)
- Display name
- Status (active, invited, suspended)
- Permissions

**Limits by Tier**:
- Free: 0 agents
- Starter: 0 agents
- Growth: 0 agents
- Pro: 2 agents

**Example**:
```
Agent: Sarah Smith
  - Email: sarah@acme.com
  - Status: active
  - Conversations handled: 45
  - Average response time: 3 minutes
```

### 6. Documents (Knowledge Base)
**Purpose**: Information for AI to reference when answering questions

**Contains**:
- File name and type
- Content (extracted text)
- Chunks (split for vector search)
- Embeddings (for semantic search)
- Status (processing, ready, failed)

**Limits by Tier**:
- Free: 3 documents
- Starter: 10 documents
- Growth: 25 documents
- Pro: 100 documents

**Example**:
```
Document: "Product Manual.pdf"
  - Size: 2.5 MB
  - Chunks: 150
  - Status: ready
  - Uploaded: 2 days ago
```

### 7. Document Chunks
**Purpose**: Split documents into searchable pieces

**Contains**:
- Text content
- Vector embedding
- Metadata (page number, section)
- Parent document reference

**Example**:
```
Chunk #789
  - Content: "To reset your password, click..."
  - Document: Product Manual.pdf
  - Page: 12
  - Embedding: [0.123, -0.456, ...]
```

### 8. Usage Counters
**Purpose**: Track resource usage for tier limits

**Contains**:
- Month (YYYY-MM)
- Messages sent
- Tokens used (AI API calls)

**Limits by Tier** (monthly):
- Free: 500 messages
- Starter: 2,000 messages
- Growth: 10,000 messages
- Pro: 50,000 messages

**Example**:
```
Usage Counter: March 2026
  - Messages: 1,234 / 50,000
  - Tokens: 456,789
  - Resets: April 1, 2026
```

### 9. Tier Changes (Audit Log)
**Purpose**: Track subscription tier changes

**Contains**:
- From tier → To tier
- Changed by (admin email)
- Reason/note
- Timestamp

**Example**:
```
Tier Change #456
  - From: free
  - To: pro
  - Changed by: admin@chatsaas.com
  - Reason: "Customer upgrade request"
  - Date: March 19, 2026
```

## Workspace Hierarchy

```
Workspace: "Acme Corp" (Pro Tier)
│
├── Owner: john@acme.com
│
├── Channels (3/4 used)
│   ├── WebChat Widget
│   ├── Telegram Bot
│   └── WhatsApp Business
│
├── Agents (1/2 used)
│   └── Sarah Smith (sarah@acme.com)
│
├── Documents (15/100 used)
│   ├── Product Manual.pdf (150 chunks)
│   ├── FAQ.docx (45 chunks)
│   └── Pricing Guide.pdf (30 chunks)
│
├── Contacts (1,234 total)
│   ├── John Doe (Telegram)
│   ├── Jane Smith (WebChat)
│   └── Bob Johnson (WhatsApp)
│
├── Conversations (45 active)
│   ├── #1234 (John Doe - active)
│   ├── #1235 (Jane Smith - escalated)
│   └── #1236 (Bob Johnson - agent)
│
├── Messages (12,345 this month)
│   └── Usage: 12,345 / 50,000
│
└── Configuration
    ├── Fallback message: "Our team will help you..."
    ├── Alert email: support@acme.com
    └── Agents enabled: Yes
```

## Multi-Tenant Isolation

**Critical**: All data is isolated by workspace_id

Every database query includes:
```sql
WHERE workspace_id = '<current_workspace_id>'
```

This ensures:
- Workspace A cannot see Workspace B's data
- Channels, contacts, conversations are isolated
- Documents and knowledge base are separate
- Usage counters are independent

## Workspace Lifecycle

### 1. Creation (Registration)
```
User registers → Workspace created → Tier set to "free"
```

### 2. Configuration
```
User adds channels → Uploads documents → Invites agents
```

### 3. Operation
```
Customers chat → AI responds → Agents handle escalations
```

### 4. Growth
```
Hit tier limits → Admin upgrades tier → More resources available
```

### 5. Management
```
Admin monitors → Views analytics → Adjusts configuration
```

## Workspace Limits Summary

| Resource | Free | Starter | Growth | Pro |
|----------|------|---------|--------|-----|
| **Channels** | 1 | 2 | 4 | 4 |
| **Agents** | 0 | 0 | 0 | 2 |
| **Documents** | 3 | 10 | 25 | 100 |
| **Messages/Month** | 500 | 2,000 | 10,000 | 50,000 |

## Key Relationships

```
User (1) ──owns──> Workspace (1)
                      │
                      ├──has──> Channels (N)
                      ├──has──> Contacts (N)
                      ├──has──> Conversations (N)
                      ├──has──> Messages (N)
                      ├──has──> Agents (N)
                      ├──has──> Documents (N)
                      ├──has──> Document Chunks (N)
                      ├──has──> Usage Counters (N)
                      └──has──> Tier Changes (N)
```

## Common Operations

### Get Workspace Info
```python
GET /api/auth/me
# Returns user info + workspace info
```

### View Workspace Resources
```python
GET /api/channels/        # List channels
GET /api/agents/          # List agents
GET /api/documents/       # List documents
GET /api/conversations/   # List conversations
```

### Check Usage
```python
GET /api/metrics/workspace/{workspace_id}
# Returns usage stats and limits
```

### Upgrade Tier (Admin Only)
```python
POST /api/admin/workspaces/change-tier
{
  "workspace_id": "uuid",
  "new_tier": "pro",
  "reason": "Customer request"
}
```

## Summary

A workspace is a **complete, isolated environment** for a business to:
- Connect multiple communication channels
- Store knowledge base documents
- Manage customer conversations
- Invite human agents
- Track usage and limits
- Configure AI behavior

Everything in ChatSaaS belongs to a workspace, making it the fundamental unit of organization and billing.
