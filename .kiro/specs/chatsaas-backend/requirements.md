# Requirements Document

## Introduction

ChatSaaS Backend is a comprehensive FastAPI-based customer support platform that enables businesses to manage multi-channel customer conversations with AI-powered responses and human agent escalation. The system provides automated customer support through AI integration, document-based knowledge retrieval (RAG), real-time communication, and a complete management interface for workspace owners and platform administrators.

## Glossary

- **Workspace**: A tenant environment containing channels, conversations, documents, and agents for a single business
- **Channel**: A communication platform integration (Telegram, WhatsApp, Instagram, WebChat)
- **Contact**: A customer identified by external_id within a specific channel and workspace
- **Conversation**: A thread of messages between a contact and the system (AI or human agent)
- **Agent**: A human support representative who can handle escalated conversations
- **Document**: A PDF or text file uploaded to provide knowledge base content for AI responses
- **Chunk**: A processed segment of document content with vector embeddings for similarity search
- **RAG_Engine**: Retrieval Augmented Generation system that uses document chunks to provide contextual AI responses
- **Escalation_Service**: System component that determines when conversations require human intervention
- **AI_Provider**: Pluggable service for LLM and embedding generation (Google, OpenAI, Groq)
- **WebSocket_Manager**: Real-time communication system for live updates
- **Platform_Admin**: Super administrator with system-wide management capabilities
- **Tier**: Subscription level defining feature and usage limits (free, starter, growth, pro)
- **WebChat_API**: Public API endpoints for website chat widget functionality
- **Message_Processor**: Core system component that handles incoming messages and orchestrates AI processing
- **Widget_ID**: Unique identifier for a workspace's webchat channel configuration
- **Session_Token**: Temporary identifier used for message threading and rate limiting in public chat sessions

## Requirements

### Requirement 1: User Authentication and Registration

**User Story:** As a business owner, I want to register and authenticate securely, so that I can access my customer support workspace.

#### Acceptance Criteria

1. WHEN a user provides valid email and password, THE Authentication_System SHALL create a new user account with bcrypt-hashed password
2. WHEN a user registers, THE Authentication_System SHALL automatically create a workspace with unique slug derived from business name
3. WHEN a user logs in with valid credentials, THE Authentication_System SHALL return a JWT token valid for 7 days
4. THE Authentication_System SHALL include user role (owner/agent) and workspace_id in JWT payload
5. WHEN an inactive user attempts to login, THE Authentication_System SHALL reject the request with appropriate error message

### Requirement 2: Multi-Channel Integration

**User Story:** As a business owner, I want to connect multiple communication channels, so that I can manage customer conversations from different platforms in one place.

#### Acceptance Criteria

1. WHEN connecting a Telegram bot, THE Channel_Manager SHALL validate the bot token via Telegram API and register webhook URL
2. WHEN connecting WhatsApp Business, THE Channel_Manager SHALL validate credentials and configure webhook with Meta API
3. WHEN connecting Instagram, THE Channel_Manager SHALL validate page access token and configure webhook with Meta API
4. WHEN creating WebChat, THE Channel_Manager SHALL generate unique widget_id and provide embeddable chat link
5. THE Channel_Manager SHALL encrypt and store all channel credentials using AES-256-CBC encryption
6. WHEN tier limits are exceeded, THE Channel_Manager SHALL reject new channel connections with descriptive error

### Requirement 3: AI-Powered Message Processing

**User Story:** As a customer, I want to receive intelligent automated responses, so that I can get help immediately without waiting for human agents.

#### Acceptance Criteria

1. WHEN a customer message is received, THE Message_Processor SHALL check maintenance mode before any other processing
2. WHEN a customer message is received, THE Message_Processor SHALL deduplicate using external_message_id to prevent duplicate processing
3. WHEN processing a customer message, THE Message_Processor SHALL check monthly token limits before making AI calls to prevent runaway costs
4. WHEN processing a customer message, THE RAG_Engine SHALL generate query embedding and search document chunks with similarity threshold of 0.75
5. WHEN relevant document chunks are found, THE RAG_Engine SHALL generate contextual response using LLM with conversation history (last 3 exchanges)
6. WHEN no relevant chunks are found, THE RAG_Engine SHALL return the workspace fallback message
7. THE Message_Processor SHALL track token usage (input/output) and update monthly workspace limits
8. WHEN monthly token limits are exceeded, THE Message_Processor SHALL stop AI processing and escalate to human agents

### Requirement 4: Escalation Detection and Management

**User Story:** As a customer, I want to be connected to a human agent when the AI cannot help, so that I can get personalized assistance for complex issues.

#### Acceptance Criteria

1. WHEN processing a customer message, THE Escalation_Service SHALL classify escalation need using LLM with confidence scoring
2. WHEN explicit escalation keywords are detected (human, agent, manager), THE Escalation_Service SHALL escalate with reason "explicit"
3. WHEN frustration or urgency patterns are detected, THE Escalation_Service SHALL escalate with reason "implicit"
4. WHEN escalation is triggered and agents are enabled, THE Escalation_Service SHALL update conversation status to "escalated" and notify agents via WebSocket
5. WHEN escalation is triggered and no agents are available, THE Escalation_Service SHALL send email alert to workspace owner
6. THE Escalation_Service SHALL send acknowledgment message to customer confirming escalation

### Requirement 5: Document Management and Processing

**User Story:** As a business owner, I want to upload knowledge documents, so that the AI can provide accurate responses based on my business information.

#### Acceptance Criteria

1. WHEN uploading a document, THE Document_Service SHALL validate file type (PDF/TXT) and size limit (10MB)
2. WHEN tier document limits are exceeded, THE Document_Service SHALL reject upload with descriptive error
3. WHEN processing a document, THE Document_Service SHALL extract text content and chunk into 500-token segments with 50-token overlap
4. FOR ALL document chunks, THE Document_Service SHALL generate embeddings using the configured embedding provider
5. THE Document_Service SHALL store chunks with vector embeddings in PostgreSQL with pgvector extension
6. WHEN document processing fails, THE Document_Service SHALL update status to "failed" with error message
7. THE Document_Service SHALL format document metadata for display in management interface
8. FOR ALL valid documents, uploading then processing then retrieving SHALL produce searchable content (round-trip property)

### Requirement 6: Agent Management and Invitation System

**User Story:** As a business owner, I want to invite human agents to handle escalated conversations, so that customers receive personalized support when needed.

#### Acceptance Criteria

1. WHERE pro tier is enabled, THE Agent_Manager SHALL allow invitation of up to 2 agents per workspace
2. WHEN inviting an agent, THE Agent_Manager SHALL generate secure invitation token with 7-day expiration
3. WHEN sending invitations, THE Email_Service SHALL deliver invitation email via Resend API with accept link
4. WHEN an agent accepts invitation, THE Agent_Manager SHALL create user account and link to agent record
5. THE Agent_Manager SHALL prevent duplicate agent emails within the same workspace
6. WHEN deactivating an agent, THE Agent_Manager SHALL update their active conversations from status 'agent' back to 'escalated' so they can be claimed by another available agent or fall through to owner email alert

### Requirement 7: Real-Time Communication System

**User Story:** As an agent, I want to receive real-time notifications of new conversations and messages, so that I can respond promptly to customers.

#### Acceptance Criteria

1. WHEN a conversation is escalated, THE WebSocket_Manager SHALL broadcast escalation event to all connected workspace clients
2. WHEN an agent claims a conversation, THE WebSocket_Manager SHALL broadcast claim event with agent information
3. WHEN a new message arrives in an active conversation, THE WebSocket_Manager SHALL broadcast message event to workspace connections
4. THE WebSocket_Manager SHALL authenticate connections using JWT token in query parameters and validate the token before accepting the connection
5. THE WebSocket_Manager SHALL maintain separate connection pools per workspace for message isolation
6. WHEN a WebSocket connection drops, THE WebSocket_Manager SHALL clean up connection references automatically

### Requirement 8: Webhook Security and Processing

**User Story:** As a platform operator, I want secure webhook endpoints, so that only legitimate channel messages are processed and malicious requests are rejected.

#### Acceptance Criteria

1. WHEN receiving Telegram webhooks, THE Webhook_Handler SHALL verify X-Telegram-Bot-Api-Secret-Token header using timing-safe comparison
2. WHEN receiving WhatsApp webhooks, THE Webhook_Handler SHALL verify HMAC-SHA256 signature using app secret
3. WHEN receiving Instagram webhooks, THE Webhook_Handler SHALL verify HMAC-SHA256 signature using app secret
4. THE Webhook_Handler SHALL return HTTP 200 immediately and process messages as background tasks
5. WHEN signature verification fails, THE Webhook_Handler SHALL reject request with HTTP 401 status
6. THE Webhook_Handler SHALL handle Meta verification challenges for WhatsApp and Instagram setup

### Requirement 9: Multi-Tier Subscription System

**User Story:** As a business owner, I want different subscription tiers with appropriate limits, so that I can choose a plan that fits my business needs and scale as I grow.

#### Acceptance Criteria

1. THE Tier_Manager SHALL enforce channel limits: free(1), starter(2), growth(4), pro(4)
2. THE Tier_Manager SHALL enforce agent limits: free(0), starter(0), growth(0), pro(2)
3. THE Tier_Manager SHALL enforce document limits: free(3), starter(10), growth(25), pro(100)
4. THE Tier_Manager SHALL enforce monthly message limits: free(500), starter(2000), growth(10000), pro(50000)
5. WHEN limits are exceeded, THE Tier_Manager SHALL prevent new resource creation with descriptive error messages
6. THE Tier_Manager SHALL track usage counters and reset monthly limits on the first day of each month

### Requirement 10: Platform Administration System

**User Story:** As a platform administrator, I want comprehensive management tools, so that I can monitor system health, manage workspaces, and provide customer support.

#### Acceptance Criteria

1. WHEN super admin email matches SUPER_ADMIN_EMAIL, THE Admin_System SHALL grant access to all administrative functions
2. THE Admin_System SHALL provide workspace overview with tier breakdown, message counts, and recent activity
3. THE Admin_System SHALL allow tier changes with audit logging to tier_changes table
4. THE Admin_System SHALL provide user management with suspend/unsuspend capabilities
5. THE Admin_System SHALL allow workspace deletion with name confirmation for safety
6. THE Admin_System SHALL provide analytics dashboard with message volume, signup trends, and escalation statistics

### Requirement 11: AI Provider Abstraction

**User Story:** As a platform operator, I want pluggable AI providers, so that I can switch between different AI services based on cost, performance, and availability requirements.

#### Acceptance Criteria

1. THE AI_Provider SHALL support Google (Gemini), OpenAI (GPT-4o-mini), and Groq (Llama) for LLM responses
2. THE AI_Provider SHALL support Google (gemini-embedding-001) and OpenAI (text-embedding-3-small) for embeddings
3. WHEN switching LLM providers, THE AI_Provider SHALL require only environment variable change without code modifications
4. WHEN switching embedding providers, THE AI_Provider SHALL require database migration and document reprocessing
5. THE AI_Provider SHALL maintain consistent interface across all providers for responses, embeddings, and classification
6. THE AI_Provider SHALL handle provider-specific message format conversions transparently

### Requirement 12: Rate Limiting and Security

**User Story:** As a platform operator, I want robust rate limiting and security measures, so that the system remains stable and protected from abuse.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL enforce 10 messages per minute per WebChat session using database-backed counters
2. THE Rate_Limiter SHALL use timing-safe comparison for all webhook signature verifications
3. THE Security_System SHALL encrypt channel credentials before database storage using AES-256-CBC
4. THE Security_System SHALL hash passwords using bcrypt with appropriate salt rounds
5. THE Security_System SHALL validate JWT tokens on all protected endpoints with proper error handling
6. WHEN maintenance mode is enabled, THE Security_System SHALL reject all non-admin requests with maintenance message

### Requirement 13: File Storage and Management

**User Story:** As a business owner, I want reliable document storage, so that my knowledge base files are safely stored and accessible for AI processing.

#### Acceptance Criteria

1. THE Storage_System SHALL save uploaded documents to local filesystem at STORAGE_PATH/documents/{workspace_id}/
2. THE Storage_System SHALL generate unique filenames to prevent conflicts and directory traversal attacks
3. THE Storage_System SHALL validate file extensions and MIME types before storage
4. WHEN deleting documents, THE Storage_System SHALL remove both database records and filesystem files
5. THE Storage_System SHALL handle concurrent access safely with appropriate file locking
6. THE Storage_System SHALL provide file size validation before processing to prevent resource exhaustion

### Requirement 14: Database Schema and Migrations

**User Story:** As a platform operator, I want a robust database schema with proper migrations, so that data integrity is maintained and schema changes are applied safely.

#### Acceptance Criteria

1. THE Database_System SHALL use PostgreSQL 15 with pgvector extension for vector similarity search
2. THE Database_System SHALL enforce foreign key constraints and unique constraints as defined in models
3. THE Database_System SHALL use Alembic for version-controlled schema migrations
4. THE Database_System SHALL support vector columns with appropriate dimensions (3072 for Google, 1536 for OpenAI)
5. THE Database_System SHALL create HNSW indexes on embedding columns for efficient similarity search
6. THE Database_System SHALL handle timezone-aware timestamps using UTC storage

### Requirement 15: Email Notification System

**User Story:** As a business owner, I want email notifications for important events, so that I stay informed about escalations and system activities even when not actively monitoring the dashboard.

#### Acceptance Criteria

1. WHEN conversations are escalated without available agents, THE Email_Service SHALL send alert to workspace owner via Resend API
2. WHEN agents are invited, THE Email_Service SHALL send invitation email with secure token and accept link
3. THE Email_Service SHALL use configured sender address from RESEND_FROM_EMAIL environment variable
4. THE Email_Service SHALL handle email delivery failures gracefully with appropriate error logging
5. THE Email_Service SHALL include relevant conversation context in escalation alert emails
6. THE Email_Service SHALL format invitation emails with business branding and clear call-to-action

### Requirement 16: WebChat Public API

**User Story:** As a website visitor, I want to interact with the chat widget, so that I can get support without creating an account.

#### Acceptance Criteria

1. THE WebChat_API SHALL provide public POST /api/webchat/send endpoint for sending messages without authentication
2. THE WebChat_API SHALL provide public GET /api/webchat/messages endpoint for polling responses without authentication  
3. THE WebChat_API SHALL rate limit webchat sessions to 10 messages per minute using database-backed counters
4. THE WebChat_API SHALL validate widget_id exists and is active before processing messages
5. THE WebChat_API SHALL use session_token for message threading and rate limiting

### Requirement 17: Public Chat Link

**User Story:** As a website visitor, I want to access a full-page chat interface, so that I can have extended conversations with customer support.

#### Acceptance Criteria

1. THE WebChat_API SHALL provide public GET /api/webchat/config/{workspace_slug} endpoint without authentication
2. THE WebChat_API SHALL return widget configuration including business_name, primary_color, position, welcome_message
3. THE WebChat_API SHALL return widget_id for the workspace to enable chat functionality
4. WHEN workspace_slug does not exist, THE WebChat_API SHALL return 404 error
5. THE WebChat_API SHALL only return configuration for active webchat channels

### Requirement 18: Maintenance Mode Enforcement

**User Story:** As a platform operator, I want to enable maintenance mode, so that I can perform system updates without causing AI processing errors or unexpected costs.

#### Acceptance Criteria

1. WHEN maintenance mode is enabled in platform_settings, THE Message_Processor SHALL check this setting before all other processing
2. WHEN maintenance mode is active, THE Message_Processor SHALL return a maintenance message to the customer without calling any AI services
3. WHEN maintenance mode is active, THE Message_Processor SHALL not perform escalation classification or RAG processing
4. WHEN maintenance mode is active, THE Message_Processor SHALL still save the customer message for later processing
5. THE Message_Processor SHALL check maintenance mode as the first step in process_message() function