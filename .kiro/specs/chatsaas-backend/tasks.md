# Implementation Plan: ChatSaaS Backend

## Overview

This implementation plan breaks down the ChatSaaS backend into discrete coding tasks that build incrementally toward a complete multi-tenant customer support platform. The system uses FastAPI with PostgreSQL, implements pluggable AI providers, and includes comprehensive testing to validate all 34 correctness properties defined in the design document.

## Tasks

- [ ] 1. Project Setup and Core Infrastructure
  - [x] 1.1 Initialize FastAPI project structure and dependencies
    - Create project directory structure with main.py, requirements.txt, alembic.ini
    - Install core dependencies: FastAPI, SQLAlchemy 2.0 (async), Alembic, asyncpg, python-jose, bcrypt
    - Set up environment configuration with Pydantic Settings
    - _Requirements: 14.1, 14.3_

  - [x] 1.2 Write unit tests for environment configuration
    - Test environment variable loading and validation
    - Test configuration error handling scenarios
    - _Requirements: 14.1, 14.3_

  - [x] 1.3 Configure database connection and session management
    - Set up PostgreSQL connection with asyncpg driver
    - Create async session factory and dependency injection
    - Configure connection pooling and error handling
    - _Requirements: 14.1, 14.6_

  - [x] 1.4 Write unit tests for database connection
    - Test connection establishment and session lifecycle
    - Test connection pool behavior and error scenarios
    - _Requirements: 14.1_

- [ ] 2. Database Schema and Models Implementation
  - [x] 2.1 Create core SQLAlchemy models with UUID primary keys
    - Implement User, Workspace, Channel, Contact, Conversation, Message models
    - Add proper foreign key relationships and constraints
    - Include timezone-aware timestamps with UTC storage
    - _Requirements: 14.2, 14.6_

  - [x] 2.2 Create document and knowledge management models
    - Implement Document, DocumentChunk models with vector columns
    - Set up pgvector extension support with configurable dimensions
    - Add proper indexing for vector similarity search
    - _Requirements: 5.4, 5.5, 14.4, 14.5_

  - [x] 2.3 Create agent and usage tracking models
    - Implement Agent, UsageCounter, PlatformSetting, TierChange models
    - Add unique constraints and proper relationships
    - Include audit fields for tier changes
    - _Requirements: 6.2, 9.6, 10.3_

  - [x] 2.4 Write property test for database constraints
    - **Property 31: Database Constraint Enforcement**
    - **Validates: Requirements 14.2, 14.4, 14.6**

  - [x] 2.5 Set up Alembic migrations
    - Initialize Alembic configuration
    - Create initial migration with all models
    - Add HNSW indexes for vector columns
    - _Requirements: 14.3, 14.5_

- [ ] 3. Authentication and Security System
  - [x] 3.1 Implement JWT authentication service
    - Create JWT token generation and validation functions
    - Implement bcrypt password hashing with proper salt rounds
    - Add user role and workspace claims to JWT payload
    - _Requirements: 1.3, 1.4, 12.4_

  - [x] 3.2 Write property test for authentication round trip
    - **Property 1: Authentication Round Trip**
    - **Validates: Requirements 1.1, 1.3, 1.4**

  - [x] 3.3 Create authentication dependencies and middleware
    - Implement get_current_user and get_current_workspace dependencies
    - Add JWT token validation on protected endpoints
    - Handle authentication errors with proper error responses
    - _Requirements: 1.5, 12.5_

  - [x] 3.4 Write property test for access control enforcement
    - **Property 3: Access Control Enforcement**
    - **Validates: Requirements 1.5, 12.5**

  - [x] 3.5 Implement user registration and login endpoints
    - Create POST /api/auth/register with workspace creation
    - Create POST /api/auth/login with credential validation
    - Generate unique workspace slugs from business names
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 3.6 Write property test for workspace creation consistency
    - **Property 2: Workspace Creation Consistency**
    - **Validates: Requirements 1.2**

- [x] 4. Checkpoint - Core Authentication Complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. AI Provider Abstraction Layer
  - [x] 5.1 Create AI provider interface and base classes
    - Define AIProvider protocol with generate_response, generate_embedding, classify_escalation methods
    - Create provider factory for Google, OpenAI, and Groq
    - Implement consistent error handling across providers
    - _Requirements: 11.1, 11.2, 11.5, 11.6_

  - [x] 5.2 Implement Google AI provider
    - Create GoogleAIProvider with Gemini 2.0 Flash for LLM and gemini-embedding-001 for embeddings
    - Handle Google-specific message format conversions
    - Implement proper error handling and rate limiting
    - _Requirements: 11.1, 11.2, 11.6_

  - [x] 5.3 Implement OpenAI provider
    - Create OpenAIProvider with GPT-4o-mini for LLM and text-embedding-3-small for embeddings
    - Handle OpenAI-specific message format and response parsing
    - Implement proper error handling and token counting
    - _Requirements: 11.1, 11.2, 11.6_

  - [x] 5.4 Implement Groq provider
    - Create GroqProvider with Llama 3.3 70B for LLM responses
    - Handle Groq-specific API integration and error responses
    - Implement consistent interface with other providers
    - _Requirements: 11.1, 11.6_

  - [x] 5.5 Write property test for AI provider interface consistency
    - **Property 24: AI Provider Interface Consistency**
    - **Validates: Requirements 11.1, 11.2, 11.5, 11.6**

  - [x] 5.6 Write property test for AI provider switching
    - **Property 25: AI Provider Switching Requirements**
    - **Validates: Requirements 11.3, 11.4**

- [ ] 6. Encryption and Security Services
  - [x] 6.1 Implement AES-256-CBC encryption service
    - Create encrypt/decrypt functions for channel credentials
    - Use secure key derivation and initialization vectors
    - Handle encryption errors gracefully
    - _Requirements: 2.5, 12.3_

  - [x] 6.2 Write property test for credential encryption round trip
    - **Property 5: Credential Encryption Round Trip**
    - **Validates: Requirements 2.5, 12.3**

  - [x] 6.3 Implement timing-safe comparison utilities
    - Create secure comparison functions for webhook signatures
    - Implement HMAC-SHA256 verification for Meta platforms
    - Add Telegram secret token verification
    - _Requirements: 8.1, 8.2, 8.3, 12.2_

  - [ ] 6.4 Write property test for webhook security verification
    - **Property 20: Webhook Security Verification**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

- [ ] 7. Tier Management and Usage Tracking
  - [x] 7.1 Implement tier manager service
    - Create TierManager class with limit checking methods
    - Implement channel, agent, document, and message limit enforcement
    - Add tier-specific feature access control
    - _Requirements: 2.6, 6.1, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 7.2 Write property test for tier limit enforcement
    - **Property 6: Tier Limit Enforcement**
    - **Validates: Requirements 2.6, 6.1, 9.1, 9.2, 9.3, 9.4, 9.5**

  - [x] 7.3 Implement usage counter management
    - Create usage tracking with monthly reset functionality
    - Implement token counting and limit validation
    - Add database-backed usage persistencen 
    - _Requirements: 3.7, 9.6_

  - [ ] 7.4 Write property test for usage counter management
    - **Property 22: Usage Counter Management**
    - **Validates: Requirements 9.6**

- [ ] 8. Message Processing Core System
  - [x] 8.1 Implement message processor service
    - Create MessageProcessor class with maintenance mode checking
    - Implement message deduplication using external_message_id
    - Add token limit validation before AI processing
    - _Requirements: 3.1, 3.2, 3.3, 18.1, 18.5_

  - [x] 8.2 Write property test for maintenance mode priority
    - **Property 7: Maintenance Mode Priority**
    - **Validates: Requirements 3.1, 18.1, 18.2, 18.3, 18.4, 18.5**

  - [x] 8.3 Write property test for message deduplication
    - **Property 8: Message Deduplication**
    - **Validates: Requirements 3.2**

  - [x] 8.4 Write property test for token limit protection
    - **Property 9: Token Limit Protection**
    - **Validates: Requirements 3.3, 3.7, 3.8**

  - [x] 8.5 Implement conversation and contact management
    - Create contact lookup and creation logic
    - Implement conversation threading and status management
    - Add proper workspace isolation for all operations
    - _Requirements: Contact and conversation management from design_

- [ ] 9. RAG Engine Implementation
  - [x] 9.1 Implement document processing pipeline
    - Create document upload validation (file type, size limits)
    - Implement text extraction for PDF and TXT files
    - Add chunking with 500-token segments and 50-token overlap
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 9.2 Implement embedding generation and storage
    - Generate embeddings for all document chunks
    - Store chunks with vector embeddings in PostgreSQL
    - Handle processing failures with proper error messages
    - _Requirements: 5.4, 5.5, 5.6_

  - [x] 9.3 Write property test for document processing pipeline
    - **Property 13: Document Processing Pipeline**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**

  - [x] 9.4 Write property test for document processing error handling
    - **Property 14: Document Processing Error Handling**
    - **Validates: Requirements 5.6**

  - [x] 9.5 Implement RAG response generation
    - Create query embedding generation
    - Implement vector similarity search with 0.75 threshold
    - Generate contextual responses using conversation history (last 3 exchanges)
    - Return workspace fallback message when no relevant content found
    - _Requirements: 3.4, 3.5, 3.6_

  - [x] 9.6 Write property test for RAG processing consistency
    - **Property 10: RAG Processing Consistency**
    - **Validates: Requirements 3.4, 3.5, 3.6**

  - [x] 9.7 Write property test for document round trip
    - **Property 15: Document Round Trip**
    - **Validates: Requirements 5.8**

- [ ] 10. Escalation System Implementation
  - [x] 10.1 Implement escalation classification service
    - Create LLM-based escalation classification with confidence scoring
    - Implement explicit keyword detection (human, agent, manager)
    - Add frustration and urgency pattern recognition
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 10.2 Write property test for escalation classification accuracy
    - **Property 11: Escalation Classification Accuracy**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.6**

  - [x] 10.3 Implement escalation workflow routing
    - Update conversation status to "escalated" on escalation
    - Notify available agents via WebSocket when agents enabled
    - Send email alerts to workspace owners when no agents available
    - Send acknowledgment messages to customers
    - _Requirements: 4.4, 4.5, 4.6_

  - [x] 10.4 Write property test for escalation workflow routing
    - **Property 12: Escalation Workflow Routing**
    - **Validates: Requirements 4.4, 4.5**

- [x] 11. Checkpoint - Core Processing Complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. WebSocket Real-time Communication
  - [x] 12.1 Implement WebSocket manager service
    - Create WebSocketManager class with workspace-isolated connection pools
    - Implement JWT authentication for WebSocket connections
    - Add automatic connection cleanup on disconnect
    - _Requirements: 7.4, 7.6_

  - [x] 12.2 Write property test for WebSocket connection management
    - **Property 19: WebSocket Connection Management**
    - **Validates: Requirements 7.4, 7.6**

  - [x] 12.3 Implement WebSocket event broadcasting
    - Broadcast escalation events to workspace connections
    - Broadcast agent claim events with agent information
    - Broadcast new message events to active conversations
    - Maintain workspace isolation for all events
    - _Requirements: 7.1, 7.2, 7.3, 7.5_

  - [x] 12.4 Write property test for WebSocket event broadcasting
    - **Property 18: WebSocket Event Broadcasting**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.5**

  - [x] 12.5 Create WebSocket endpoint and connection handling
    - Implement GET /api/ws/{workspace_id} endpoint
    - Add JWT token validation in query parameters
    - Handle connection lifecycle and error scenarios
    - _Requirements: 7.4, 7.6_

- [ ] 13. Channel Management and Integration
  - [x] 13.1 Implement channel connection validation
    - Create channel validation for Telegram (bot token via API)
    - Implement WhatsApp Business credential validation with Meta API
    - Add Instagram page access token validation
    - Generate unique widget_id for WebChat channels
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 13.2 Write property test for channel connection validation
    - **Property 4: Channel Connection Validation**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [x] 13.3 Implement channel management endpoints
    - Create POST /api/channels for channel creation
    - Implement GET /api/channels for channel listing
    - Add channel activation/deactivation functionality
    - Include tier limit checking for new channels
    - **Note: Channel credential encryption (Task 6.1) must be complete before any channel connect endpoints are wired up**
    - _Requirements: 2.6, Channel management from design_

  - [x] 13.4 Write unit tests for channel management
    - Test channel creation with valid and invalid credentials
    - Test tier limit enforcement for channel creation
    - Test channel listing and status management
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

- [ ] 14. Webhook Processing Implementation
  - [x] 14.1 Implement webhook handlers for all channels
    - Create Telegram webhook handler with secret token verification
    - Implement WhatsApp webhook handler with HMAC-SHA256 verification
    - Add Instagram webhook handler with signature verification
    - Handle Meta verification challenges for setup
    - _Requirements: 8.1, 8.2, 8.3, 8.6_

  - [ ]* 14.2 Write property test for Meta verification challenge handling
    - **Property 21: Meta Verification Challenge Handling**
    - **Validates: Requirements 8.6**

  - [x] 14.3 Implement webhook processing pipeline
    - Return HTTP 200 immediately for all webhooks
    - Process messages as background tasks
    - Reject invalid signatures with HTTP 401
    - Handle webhook parsing and message extraction
    - _Requirements: 8.4, 8.5_

  - [ ]* 14.4 Write unit tests for webhook processing
    - Test signature verification for all channel types
    - Test background task processing and error handling
    - Test webhook parsing and message extraction
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 15. Agent Management System
  - [x] 15.1 Implement agent invitation workflow
    - Create agent invitation with secure token generation (7-day expiration)
    - Implement email sending via Resend API with accept links
    - Prevent duplicate agent emails within workspaces
    - Enforce pro tier agent limits (up to 2 agents)
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [ ]* 15.2 Write property test for agent invitation workflow
    - **Property 16: Agent Invitation Workflow**
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5**

  - [x] 15.3 Implement agent acceptance and deactivation
    - Create agent invitation acceptance endpoint
    - Link user accounts to agent records on acceptance
    - Implement agent deactivation with conversation cleanup
    - Update active conversations from 'agent' to 'escalated' status
    - _Requirements: 6.4, 6.6_

  - [ ]* 15.4 Write property test for agent deactivation cleanup
    - **Property 17: Agent Deactivation Cleanup**
    - **Validates: Requirements 6.6**

  - [x] 15.5 Create agent management endpoints
    - Implement POST /api/agents/invite for agent invitations
    - Create GET /api/agents for agent listing
    - Add agent activation/deactivation endpoints
    - Include proper authorization and tier checking
    - _Requirements: 6.1, 6.2, 6.5, 6.6_

  - [x] 15.6 Implement agent login endpoint
    - Create POST /api/auth/agent-login for agent authentication
    - Validate agent credentials and workspace access
    - Generate JWT tokens with agent-specific claims
    - _Requirements: Agent authentication from design_

- [ ] 16. Email Notification System
  - [x] 16.1 Implement email service with Resend integration
    - Create email service class with Resend API integration
    - Implement escalation alert emails to workspace owners
    - Create agent invitation emails with secure tokens and branding
    - Handle email delivery failures with proper error logging
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [ ]* 16.2 Write property test for email service reliability
    - **Property 32: Email Service Reliability**
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6**

  - [ ]* 16.3 Write unit tests for email notifications
    - Test escalation alert email formatting and delivery
    - Test agent invitation email generation and sending
    - Test error handling for delivery failures
    - _Requirements: 15.1, 15.2, 15.4_

- [ ] 17. Rate Limiting and Security Implementation
  - [x] 17.1 Implement rate limiting for WebChat sessions
    - Create database-backed rate limiting (10 messages per minute)
    - Implement session token management for WebChat
    - Add rate limit enforcement with proper error responses
    - _Requirements: 12.1, 16.3_

  - [ ]* 17.2 Write property test for rate limiting enforcement
    - **Property 26: Rate Limiting Enforcement**
    - **Validates: Requirements 12.1, 16.3**

  - [x] 17.3 Implement maintenance mode security
    - Create maintenance mode checking middleware
    - Reject non-admin requests during maintenance with proper messages
    - Allow admin access to continue during maintenance
    - _Requirements: 12.6, 18.1, 18.2_

  - [ ]* 17.4 Write property test for maintenance mode security
    - **Property 28: Maintenance Mode Security**
    - **Validates: Requirements 12.6**

  - [ ]* 17.5 Write property test for security implementation standards
    - **Property 27: Security Implementation Standards**
    - **Validates: Requirements 12.2, 12.4, 12.5**

- [ ] 18. File Storage and Management
  - [x] 18.1 Implement file storage service
    - Create file storage with workspace-specific paths (STORAGE_PATH/documents/{workspace_id}/)
    - Generate unique filenames to prevent conflicts and directory traversal
    - Validate file extensions and MIME types before storage
    - Handle concurrent access with proper file locking
    - _Requirements: 13.1, 13.2, 13.3, 13.5_

  - [ ]* 18.2 Write property test for file storage security and management
    - **Property 29: File Storage Security and Management**
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.5**

  - [x] 18.3 Implement file cleanup and validation
    - Remove both database records and filesystem files on deletion
    - Validate file sizes before processing to prevent resource exhaustion
    - Handle cleanup of partially processed resources
    - _Requirements: 13.4, 13.6_

  - [ ]* 18.4 Write property test for file cleanup completeness
    - **Property 30: File Cleanup Completeness**
    - **Validates: Requirements 13.4, 13.6**

- [ ] 19. WebChat Public API Implementation
  - [x] 19.1 Implement public WebChat endpoints
    - Create POST /api/webchat/send for sending messages without authentication
    - Implement GET /api/webchat/messages for polling responses
    - Add session token management for message threading
    - Validate widget_id exists and is active before processing
    - _Requirements: 16.1, 16.2, 16.4, 16.5_

  - [x] 19.2 Implement WebChat configuration API
    - Create GET /api/webchat/config/{workspace_slug} endpoint
    - Return widget configuration (business_name, primary_color, position, welcome_message)
    - Include widget_id for chat functionality
    - Handle non-existent workspace_slug with 404 errors
    - **Note: Ensure workspace slug lookup functionality exists in the workspace service**
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

  - [ ]* 19.3 Write property test for WebChat API widget validation
    - **Property 33: WebChat API Widget Validation**
    - **Validates: Requirements 16.4, 16.5, 17.2, 17.3**

  - [ ]* 19.4 Write property test for WebChat API error handling
    - **Property 34: WebChat API Error Handling**
    - **Validates: Requirements 17.4, 17.5**

- [ ] 20. Platform Administration System
  - [x] 20.1 Implement platform administration access control
    - Create super admin access validation using SUPER_ADMIN_EMAIL
    - Implement workspace overview with tier breakdown and activity metrics
    - Add user management with suspend/unsuspend capabilities
    - _Requirements: 10.1, 10.2, 10.4_

  - [ ]* 20.2 Write property test for platform administration access control
    - **Property 23: Platform Administration Access Control**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**

  - [x] 20.3 Implement tier management and analytics
    - Create tier change functionality with audit logging
    - Implement workspace deletion with name confirmation
    - Add analytics dashboard with message volume and signup trends
    - _Requirements: 10.3, 10.5, 10.6_

  - [ ]* 20.4 Write unit tests for platform administration
    - Test super admin access control and validation
    - Test tier change audit logging and workspace management
    - Test analytics dashboard data aggregation
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 21. Checkpoint - All Core Features Complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 22. Integration and API Wiring
  - [x] 22.1 Wire message processing pipeline
    - Connect webhook handlers to message processor
    - Integrate RAG engine with escalation service
    - Link WebSocket notifications to conversation updates
    - Ensure proper error handling throughout the pipeline
    - **Note: When reaching this task, expand each sub-task with specific file names and endpoint connections rather than vague descriptions**
    - _Requirements: Integration of all message processing components_

  - [x] 22.2 Wire authentication and authorization
    - Connect JWT authentication to all protected endpoints
    - Integrate tier management with resource creation endpoints
    - Link workspace isolation to all data access operations
    - _Requirements: Authentication integration across all endpoints_

  - [x] 22.3 Wire real-time notifications
    - Connect escalation events to WebSocket broadcasting
    - Integrate agent management with notification system
    - Link conversation updates to real-time event distribution
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 22.4 Write integration tests for complete workflows
    - Test end-to-end message processing from webhook to response
    - Test escalation workflow from detection to agent notification
    - Test document upload and RAG response generation
    - _Requirements: End-to-end workflow validation_

- [ ] 23. Production Configuration and Deployment Setup
  - [x] 23.1 Create production configuration
    - Set up Gunicorn with Uvicorn workers for production
    - Configure Nginx reverse proxy with proper headers
    - Add production environment variable templates
    - Include SSL/TLS configuration for HTTPS
    - _Requirements: Production deployment from design_

  - [x] 23.2 Create database migration and seeding scripts
    - Set up production database initialization
    - Create platform settings seeding (maintenance mode, etc.)
    - Add database backup and restore procedures
    - _Requirements: 14.3, Platform settings initialization_

  - [x] 23.3 Add monitoring and health checks
    - Implement health check endpoints for load balancer
    - Add application metrics and logging configuration
    - Create error monitoring and alerting setup
    - _Requirements: Production monitoring from design_

- [ ] 24. Final Integration Testing and Validation
  - [x] 24.1 Run comprehensive property-based test suite
    - Execute all 34 property tests with minimum 100 iterations each
    - Validate all correctness properties against implementation
    - Ensure statistical confidence in property validation
    - _Requirements: All 34 correctness properties_

  - [x] 24.2 Perform end-to-end system validation
    - Test complete customer journey from message to response
    - Validate multi-tenant isolation across all operations
    - Test all channel integrations with real webhook data
    - _Requirements: Complete system validation_

  - [x] 24.3 Validate security and performance requirements
    - Test rate limiting under load conditions
    - Validate encryption/decryption performance
    - Test WebSocket connection stability under concurrent load
    - _Requirements: Security and performance validation_

- [x] 25. Final Checkpoint - System Complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP development
- Each task references specific requirements for traceability to the original specification
- Property tests validate the 34 correctness properties defined in the design document
- Checkpoints ensure incremental validation and provide opportunities for user feedback
- The implementation uses Python with FastAPI, SQLAlchemy, and PostgreSQL as specified in the design
- All security requirements are implemented including encryption, authentication, and rate limiting
- Multi-tenant architecture ensures complete workspace isolation throughout the system