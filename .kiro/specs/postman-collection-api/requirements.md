# Requirements Document

## Introduction

This document specifies requirements for creating a comprehensive Postman collection that covers all API endpoints and functionality in the ChatSaaS backend. The collection will enable developers, QA engineers, and API consumers to test, explore, and integrate with the ChatSaaS API efficiently.

## Glossary

- **Postman_Collection**: A JSON file containing organized API requests, environment variables, tests, and documentation for the Postman API client
- **Collection_Generator**: The system component that generates the Postman collection from API documentation
- **Environment_Variables**: Configurable values in Postman for base URLs, tokens, and resource IDs
- **Pre_Request_Script**: JavaScript code executed before a request to set up authentication or variables
- **Test_Script**: JavaScript code executed after a response to validate status codes and response data
- **Request_Folder**: A logical grouping of related API endpoints within the collection
- **Example_Response**: Sample response data stored with each request for documentation purposes
- **WebSocket_Documentation**: Descriptive documentation for WebSocket connections since Postman has limited WebSocket support

## Requirements

### Requirement 1: Collection Structure and Organization

**User Story:** As a developer, I want the Postman collection organized by logical API groups, so that I can quickly find and test specific endpoints.

#### Acceptance Criteria

1. THE Collection_Generator SHALL create a collection with folders matching the API documentation structure (Authentication, Channel Management, Document Management, Agent Management, Conversation Management, Webhooks, WebSocket, WebChat Public API, Platform Administration, Metrics & Monitoring)
2. WHEN organizing endpoints, THE Collection_Generator SHALL place each endpoint in its corresponding folder based on the base URL path
3. THE Collection_Generator SHALL name each request using the format "{HTTP_METHOD} {endpoint_name}" for clarity
4. THE Collection_Generator SHALL order requests within folders to match the sequence in the API documentation

### Requirement 2: Authentication Endpoints

**User Story:** As a developer, I want all authentication endpoints included, so that I can test user registration, login, and token management.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include POST /api/auth/register with example request body containing email, password, and business_name
2. THE Collection_Generator SHALL include POST /api/auth/login with example request body containing email and password
3. THE Collection_Generator SHALL include POST /api/auth/agent-login with example request body for agent authentication
4. THE Collection_Generator SHALL include POST /api/auth/accept-invite with invitation token in request body
5. THE Collection_Generator SHALL include GET /api/auth/me with Authorization header placeholder
6. WHEN a login request succeeds, THE Collection_Generator SHALL include a test script that extracts and saves the access_token to an environment variable

### Requirement 3: Channel Management Endpoints

**User Story:** As a developer, I want all channel management endpoints included with examples for each channel type, so that I can test channel creation and configuration.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include POST /api/channels with separate example requests for Telegram, WhatsApp, Instagram, and WebChat channel types
2. THE Collection_Generator SHALL include GET /api/channels for listing all channels
3. THE Collection_Generator SHALL include GET /api/channels/{channel_id} with channel_id as a path variable
4. THE Collection_Generator SHALL include PUT /api/channels/{channel_id} with example update payload
5. THE Collection_Generator SHALL include DELETE /api/channels/{channel_id}
6. THE Collection_Generator SHALL include POST /api/channels/validate/{channel_type} for each supported channel type
7. THE Collection_Generator SHALL include GET /api/channels/stats/summary
8. WHEN creating a channel, THE Collection_Generator SHALL include a test script that extracts and saves the channel_id to an environment variable

### Requirement 4: Document Management Endpoints

**User Story:** As a developer, I want document management endpoints with file upload examples, so that I can test document processing workflows.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include POST /api/documents/upload with multipart/form-data content type and file parameter
2. THE Collection_Generator SHALL include GET /api/documents with query parameters for status_filter, limit, and offset
3. THE Collection_Generator SHALL include GET /api/documents/{document_id} with document_id as a path variable
4. THE Collection_Generator SHALL include DELETE /api/documents/{document_id}
5. THE Collection_Generator SHALL include POST /api/documents/{document_id}/reprocess
6. THE Collection_Generator SHALL include GET /api/documents/stats/summary
7. WHEN uploading a document, THE Collection_Generator SHALL include a test script that extracts and saves the document_id to an environment variable

### Requirement 5: Agent Management Endpoints

**User Story:** As a developer, I want agent management endpoints included, so that I can test agent invitation and lifecycle workflows.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include POST /api/agents/invite with email and name in request body
2. THE Collection_Generator SHALL include POST /api/agents/accept with invitation_token in request body
3. THE Collection_Generator SHALL include GET /api/agents with include_inactive query parameter
4. THE Collection_Generator SHALL include GET /api/agents/pending for listing pending invitations
5. THE Collection_Generator SHALL include POST /api/agents/{agent_id}/deactivate
6. THE Collection_Generator SHALL include POST /api/agents/{agent_id}/activate
7. THE Collection_Generator SHALL include POST /api/agents/{agent_id}/resend
8. THE Collection_Generator SHALL include DELETE /api/agents/{agent_id}
9. THE Collection_Generator SHALL include GET /api/agents/stats
10. THE Collection_Generator SHALL include GET /api/agents/invitation/{invitation_token} as a public endpoint without authentication
11. WHEN inviting an agent, THE Collection_Generator SHALL include a test script that extracts and saves the agent_id and invitation_token to environment variables

### Requirement 6: Conversation Management Endpoints

**User Story:** As a developer, I want conversation management endpoints included, so that I can test conversation workflows and agent interactions.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include GET /api/conversations with query parameters for status, assigned_to_me, limit, and offset
2. THE Collection_Generator SHALL include GET /api/conversations/{conversation_id} with conversation_id as a path variable
3. THE Collection_Generator SHALL include POST /api/conversations/claim with conversation_id in request body
4. THE Collection_Generator SHALL include POST /api/conversations/status with conversation_id, status, and note in request body
5. THE Collection_Generator SHALL include POST /api/conversations/{conversation_id}/messages with content in request body
6. THE Collection_Generator SHALL include GET /api/conversations/stats/summary
7. THE Collection_Generator SHALL include GET /api/conversations/my/active with pagination parameters
8. WHEN listing conversations, THE Collection_Generator SHALL include a test script that extracts and saves the first conversation_id to an environment variable

### Requirement 7: Webhook Endpoints

**User Story:** As a developer, I want webhook endpoints documented, so that I can understand webhook integration requirements.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include POST /webhooks/telegram/{bot_token} with example Telegram Update payload
2. THE Collection_Generator SHALL include POST /webhooks/whatsapp/{phone_number_id} with example WhatsApp webhook payload
3. THE Collection_Generator SHALL include GET /webhooks/whatsapp/{phone_number_id} with hub.challenge and hub.verify_token query parameters
4. THE Collection_Generator SHALL include POST /webhooks/instagram/{page_id} with example Instagram webhook payload
5. THE Collection_Generator SHALL include GET /webhooks/instagram/{page_id} with hub.challenge and hub.verify_token query parameters
6. THE Collection_Generator SHALL include GET /webhooks/health
7. THE Collection_Generator SHALL include POST /webhooks/test/{channel_type} with authentication header
8. THE Collection_Generator SHALL document in request descriptions that webhook endpoints use platform-specific signature verification

### Requirement 8: WebChat Public API Endpoints

**User Story:** As a developer, I want WebChat public API endpoints included, so that I can test widget integration without authentication.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include GET /api/webchat/config/{workspace_slug} with workspace_slug as a path variable
2. THE Collection_Generator SHALL include POST /api/webchat/send with widget_id, session_token, message, and contact_name in request body
3. THE Collection_Generator SHALL include GET /api/webchat/messages with widget_id, session_token, limit, and offset as query parameters
4. THE Collection_Generator SHALL document these endpoints as public (no authentication required)
5. WHEN sending a WebChat message, THE Collection_Generator SHALL include a test script that extracts and saves the session_token to an environment variable

### Requirement 9: Platform Administration Endpoints

**User Story:** As a platform administrator, I want admin endpoints included, so that I can test platform management operations.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include GET /api/admin/overview with super admin authentication
2. THE Collection_Generator SHALL include GET /api/admin/workspaces with query parameters for limit, offset, and tier
3. THE Collection_Generator SHALL include GET /api/admin/users with query parameters for limit, offset, and active_only
4. THE Collection_Generator SHALL include POST /api/admin/users/suspend with user_id in request body
5. THE Collection_Generator SHALL include POST /api/admin/users/unsuspend with user_id in request body
6. THE Collection_Generator SHALL include POST /api/admin/workspaces/change-tier with workspace_id, new_tier, and reason in request body
7. THE Collection_Generator SHALL include GET /api/admin/tier-changes with query parameters for workspace_id and limit
8. THE Collection_Generator SHALL include DELETE /api/admin/workspaces/delete with workspace_id and confirmation_name in request body
9. THE Collection_Generator SHALL include GET /api/admin/analytics
10. THE Collection_Generator SHALL document in folder description that all admin endpoints require super admin role

### Requirement 10: Metrics and Monitoring Endpoints

**User Story:** As a developer, I want metrics and monitoring endpoints included, so that I can test health checks and system monitoring.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include GET /api/metrics/health/detailed as a public endpoint
2. THE Collection_Generator SHALL include GET /api/metrics/system with authentication
3. THE Collection_Generator SHALL include GET /api/metrics/workspace/{workspace_id} with workspace_id as a path variable
4. THE Collection_Generator SHALL include GET /api/metrics/prometheus as a public endpoint with text/plain response
5. THE Collection_Generator SHALL include GET /api/metrics/alerts/status with authentication
6. THE Collection_Generator SHALL include test scripts that validate response status codes are 200 or 503 for health endpoints

### Requirement 11: Environment Variables Configuration

**User Story:** As a developer, I want environment variables configured, so that I can easily switch between development, staging, and production environments.

#### Acceptance Criteria

1. THE Collection_Generator SHALL create environment variables for base_url with default value "http://localhost:8000"
2. THE Collection_Generator SHALL create environment variables for access_token, workspace_id, channel_id, document_id, agent_id, conversation_id, session_token, and invitation_token with empty default values
3. THE Collection_Generator SHALL create environment variables for workspace_slug and widget_id for WebChat testing
4. THE Collection_Generator SHALL use {{base_url}} variable in all request URLs
5. THE Collection_Generator SHALL use {{access_token}} in Authorization headers where authentication is required
6. THE Collection_Generator SHALL use appropriate environment variables for path parameters and request bodies

### Requirement 12: Authentication Pre-Request Scripts

**User Story:** As a developer, I want pre-request scripts that automatically add authentication headers, so that I don't have to manually configure each request.

#### Acceptance Criteria

1. WHEN a request requires authentication, THE Collection_Generator SHALL include a pre-request script that sets the Authorization header to "Bearer {{access_token}}"
2. THE Collection_Generator SHALL document in the collection description that users must first run a login request to obtain an access_token
3. THE Collection_Generator SHALL exclude authentication headers from public endpoints (webhooks, WebChat public API, health checks)

### Requirement 13: Response Validation Test Scripts

**User Story:** As a developer, I want test scripts that validate responses, so that I can verify API behavior automatically.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include test scripts that validate response status code is 200 for successful requests
2. THE Collection_Generator SHALL include test scripts that validate response has expected fields (e.g., access_token for login, id for resource creation)
3. THE Collection_Generator SHALL include test scripts that validate response Content-Type is application/json for JSON endpoints
4. WHEN a request creates a resource, THE Collection_Generator SHALL include a test script that validates the response contains an id field
5. THE Collection_Generator SHALL include test scripts that save important response values to environment variables for use in subsequent requests

### Requirement 14: Example Requests and Responses

**User Story:** As a developer, I want example requests and responses included, so that I can understand expected data formats without reading separate documentation.

#### Acceptance Criteria

1. THE Collection_Generator SHALL include example request bodies for all POST and PUT endpoints matching the API documentation examples
2. THE Collection_Generator SHALL include example success responses (200 status) for each endpoint
3. THE Collection_Generator SHALL include example error responses (400, 401, 403, 404, 402, 429) as additional examples where documented
4. THE Collection_Generator SHALL include descriptions for each request explaining the endpoint purpose and parameters
5. THE Collection_Generator SHALL include descriptions for path variables and query parameters

### Requirement 15: WebSocket Connection Documentation

**User Story:** As a developer, I want WebSocket connection details documented, so that I can implement WebSocket clients even though Postman has limited WebSocket support.

#### Acceptance Criteria

1. THE Collection_Generator SHALL create a WebSocket folder in the collection
2. THE Collection_Generator SHALL include a documentation-only request describing the WebSocket connection URL format: ws://{{base_url}}/ws/{workspace_id}?token={{access_token}}
3. THE Collection_Generator SHALL document all client-to-server message types (ping, subscribe, get_stats, get_conversations, get_agents) with example JSON payloads
4. THE Collection_Generator SHALL document all server-to-client message types (pong, subscription_confirmed, escalation, agent_claim, new_message, conversation_status_change, error) with example JSON payloads
5. THE Collection_Generator SHALL include GET /ws/health, GET /ws/connections/{workspace_id}, and POST /ws/broadcast/{workspace_id} as REST endpoints for WebSocket management
6. THE Collection_Generator SHALL document that WebSocket connections require JWT authentication via query parameter

### Requirement 16: Collection Metadata and Documentation

**User Story:** As a developer, I want collection-level documentation, so that I can understand how to use the collection effectively.

#### Acceptance Criteria

1. THE Collection_Generator SHALL set the collection name to "ChatSaaS Backend API"
2. THE Collection_Generator SHALL include a collection description explaining the purpose, authentication requirements, and how to get started
3. THE Collection_Generator SHALL include version information in the collection description matching the API version (1.0)
4. THE Collection_Generator SHALL include instructions for setting up environment variables before using the collection
5. THE Collection_Generator SHALL include a link to the full API documentation in the collection description
6. THE Collection_Generator SHALL document tier limits and rate limiting behavior in the collection description

### Requirement 17: Error Response Documentation

**User Story:** As a developer, I want error responses documented, so that I can understand and handle API errors correctly.

#### Acceptance Criteria

1. THE Collection_Generator SHALL document the standard error response format with detail field in the collection description
2. THE Collection_Generator SHALL include example responses for common error codes (400, 401, 403, 404, 402, 413, 429, 500, 503) where applicable
3. THE Collection_Generator SHALL document rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset) in WebChat endpoint descriptions
4. THE Collection_Generator SHALL document tier limit errors (402 Payment Required) in endpoints that enforce tier limits

### Requirement 18: Postman Collection Format Compliance

**User Story:** As a developer, I want the collection in valid Postman Collection v2.1 format, so that I can import it into Postman without errors.

#### Acceptance Criteria

1. THE Collection_Generator SHALL generate a JSON file conforming to Postman Collection Format v2.1 schema
2. THE Collection_Generator SHALL include required fields: info (name, schema), item (array of requests and folders)
3. THE Collection_Generator SHALL structure folders using the item array with nested item arrays for requests
4. THE Collection_Generator SHALL format requests with method, header, url, body, and response fields
5. WHEN the collection is imported into Postman, THE Postman_Application SHALL successfully parse and display all requests without errors

### Requirement 19: Collection Export and Versioning

**User Story:** As a developer, I want the collection file versioned and easily accessible, so that I can track changes and share it with team members.

#### Acceptance Criteria

1. THE Collection_Generator SHALL save the collection file as "ChatSaaS_Backend_API.postman_collection.json" in the backend directory
2. THE Collection_Generator SHALL include a version field in the collection info matching the API version
3. THE Collection_Generator SHALL include a timestamp or date in the collection description indicating when it was generated
4. THE Collection_Generator SHALL format the JSON file with proper indentation (2 or 4 spaces) for readability

### Requirement 20: Pagination and Query Parameter Examples

**User Story:** As a developer, I want pagination and query parameters properly configured, so that I can test list endpoints with different filters.

#### Acceptance Criteria

1. WHEN an endpoint supports pagination, THE Collection_Generator SHALL include limit and offset query parameters with example values
2. THE Collection_Generator SHALL include query parameters for filtering (status, tier, active_only) where documented
3. THE Collection_Generator SHALL document default values for query parameters in request descriptions
4. THE Collection_Generator SHALL include test scripts that validate pagination response fields (total_count, has_more) where applicable
5. THE Collection_Generator SHALL use Postman query parameter format with key-value pairs and optional disabled state for optional parameters
