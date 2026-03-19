# Design Document: Postman Collection API

## Overview

This design document specifies the structure and implementation approach for generating a comprehensive Postman Collection v2.1 JSON file that covers all ChatSaaS Backend API endpoints. The collection will serve as an interactive API documentation and testing tool for developers, QA engineers, and API consumers.

The collection will be organized into logical folders matching the API structure, include authentication workflows, provide example requests and responses, and incorporate test scripts for automated validation. The design focuses on creating a single, well-structured JSON file that can be imported directly into Postman without requiring additional configuration beyond setting environment variables.

### Key Design Goals

1. **Comprehensive Coverage**: Include all 80+ API endpoints across 10 functional areas
2. **Developer Experience**: Provide clear organization, examples, and documentation within the collection
3. **Automation Ready**: Include pre-request scripts for authentication and test scripts for response validation
4. **Environment Flexibility**: Support multiple environments (dev, staging, production) through variables
5. **Standards Compliance**: Conform to Postman Collection Format v2.1 specification

### Scope

**In Scope:**
- Complete REST API endpoint coverage
- WebSocket connection documentation (descriptive, not executable)
- Authentication workflows and token management
- Environment variable configuration
- Pre-request and test scripts
- Example requests and responses for all endpoints
- Error response documentation

**Out of Scope:**
- Automated collection generation from OpenAPI/Swagger specs
- Dynamic collection updates based on code changes
- Custom Postman plugins or extensions
- Performance testing configurations
- Mock server setup

## Architecture

### Collection Structure

The Postman collection follows a hierarchical folder structure that mirrors the API's functional organization:

```
ChatSaaS Backend API (Collection Root)
├── Authentication
│   ├── POST Register
│   ├── POST Login
│   ├── POST Agent Login
│   ├── POST Accept Invite
│   └── GET Me
├── Channel Management
│   ├── POST Create Channel
│   │   ├── Example: Telegram Channel
│   │   ├── Example: WhatsApp Channel
│   │   ├── Example: Instagram Channel
│   │   └── Example: WebChat Channel
│   ├── GET List Channels
│   ├── GET Channel by ID
│   ├── PUT Update Channel
│   ├── DELETE Channel
│   ├── POST Validate Telegram
│   ├── POST Validate WhatsApp
│   ├── POST Validate Instagram
│   ├── POST Validate WebChat
│   └── GET Channel Stats
├── Document Management
│   ├── POST Upload Document
│   ├── GET List Documents
│   ├── GET Document by ID
│   ├── DELETE Document
│   ├── POST Reprocess Document
│   └── GET Document Stats
├── Agent Management
│   ├── POST Invite Agent
│   ├── POST Accept Invitation
│   ├── GET List Agents
│   ├── GET Pending Invitations
│   ├── POST Deactivate Agent
│   ├── POST Activate Agent
│   ├── POST Resend Invitation
│   ├── DELETE Agent
│   ├── GET Agent Stats
│   └── GET Validate Invitation (Public)
├── Conversation Management
│   ├── GET List Conversations
│   ├── GET Conversation by ID
│   ├── POST Claim Conversation
│   ├── POST Update Status
│   ├── POST Send Message
│   ├── GET Conversation Stats
│   └── GET My Active Conversations
├── Webhooks
│   ├── POST Telegram Webhook
│   ├── POST WhatsApp Webhook
│   ├── GET WhatsApp Verification
│   ├── POST Instagram Webhook
│   ├── GET Instagram Verification
│   ├── GET Webhook Health
│   └── POST Test Webhook
├── WebSocket
│   ├── Connection Documentation
│   ├── GET WebSocket Health
│   ├── GET Workspace Connections
│   └── POST Broadcast Message
├── WebChat Public API
│   ├── GET Widget Config
│   ├── POST Send Message
│   └── GET Messages
├── Platform Administration
│   ├── GET Overview
│   ├── GET Workspaces
│   ├── GET Users
│   ├── POST Suspend User
│   ├── POST Unsuspend User
│   ├── POST Change Tier
│   ├── GET Tier Changes
│   ├── DELETE Workspace
│   └── GET Analytics
└── Metrics & Monitoring
    ├── GET Detailed Health
    ├── GET System Metrics
    ├── GET Workspace Metrics
    ├── GET Prometheus Metrics
    └── GET Alert Status
```

### Postman Collection Format v2.1

The collection conforms to the Postman Collection Format v2.1 schema, which defines the following top-level structure:

```json
{
  "info": {
    "name": "Collection Name",
    "description": "Collection description",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    "version": "1.0.0"
  },
  "item": [],
  "variable": [],
  "auth": {},
  "event": []
}
```

**Key Schema Elements:**

- **info**: Metadata about the collection (name, description, version, schema URL)
- **item**: Array of folders and requests (recursive structure)
- **variable**: Collection-level variables (not used; we use environment variables instead)
- **auth**: Collection-level authentication (not used; we use per-request auth)
- **event**: Collection-level scripts (not used; we use per-request scripts)

### Request Structure

Each request in the collection follows this structure:

```json
{
  "name": "Request Name",
  "request": {
    "method": "GET|POST|PUT|DELETE",
    "header": [],
    "url": {
      "raw": "{{base_url}}/api/endpoint",
      "host": ["{{base_url}}"],
      "path": ["api", "endpoint"],
      "query": [],
      "variable": []
    },
    "body": {},
    "description": "Request description"
  },
  "response": [],
  "event": []
}
```

**Request Components:**

- **name**: Human-readable request name (format: "{METHOD} {endpoint_name}")
- **method**: HTTP method
- **header**: Array of header objects with key-value pairs
- **url**: URL object with raw string, host array, path array, query parameters, and path variables
- **body**: Request body (for POST/PUT requests)
- **description**: Markdown-formatted description of the endpoint
- **response**: Array of example responses
- **event**: Array of pre-request and test scripts

### Folder Structure

Folders are represented as items with nested item arrays:

```json
{
  "name": "Folder Name",
  "item": [
    // Nested requests or folders
  ],
  "description": "Folder description"
}
```

### Environment Variables

Environment variables are defined separately from the collection and include:

| Variable | Description | Default Value |
|----------|-------------|---------------|
| `base_url` | API base URL | `http://localhost:8000` |
| `access_token` | JWT authentication token | (empty) |
| `workspace_id` | Current workspace ID | (empty) |
| `workspace_slug` | Current workspace slug | (empty) |
| `channel_id` | Current channel ID | (empty) |
| `document_id` | Current document ID | (empty) |
| `agent_id` | Current agent ID | (empty) |
| `conversation_id` | Current conversation ID | (empty) |
| `session_token` | WebChat session token | (empty) |
| `widget_id` | WebChat widget ID | (empty) |
| `invitation_token` | Agent invitation token | (empty) |

These variables enable:
- Easy switching between environments (dev, staging, production)
- Automatic token management through test scripts
- Request chaining (using IDs from previous responses)

## Components and Interfaces

### Collection Generator Component

While the actual implementation will be manual JSON creation, we conceptualize the structure as if generated by a component with these responsibilities:

**Inputs:**
- API documentation (API_DOCUMENTATION.md)
- Requirements specification (requirements.md)
- Postman Collection v2.1 schema

**Outputs:**
- ChatSaaS_Backend_API.postman_collection.json

**Processing Logic:**
1. Parse API documentation to extract endpoints, parameters, and examples
2. Organize endpoints into folder hierarchy
3. Generate request objects with proper URL structure and variables
4. Create pre-request scripts for authentication
5. Create test scripts for response validation and variable extraction
6. Add example responses for success and error cases
7. Format and validate against Postman Collection v2.1 schema

### Request Builder Interface

Each request is built with the following interface:

```typescript
interface PostmanRequest {
  name: string;
  request: {
    method: "GET" | "POST" | "PUT" | "DELETE";
    header: Header[];
    url: Url;
    body?: Body;
    description?: string;
  };
  response: Response[];
  event: Event[];
}

interface Header {
  key: string;
  value: string;
  type: "text";
  disabled?: boolean;
}

interface Url {
  raw: string;
  host: string[];
  path: string[];
  query?: QueryParam[];
  variable?: PathVariable[];
}

interface QueryParam {
  key: string;
  value: string;
  disabled?: boolean;
  description?: string;
}

interface PathVariable {
  key: string;
  value: string;
  description?: string;
}

interface Body {
  mode: "raw" | "formdata" | "urlencoded";
  raw?: string;
  formdata?: FormDataParam[];
  options?: {
    raw?: {
      language: "json" | "text";
    };
  };
}

interface Response {
  name: string;
  originalRequest: PostmanRequest["request"];
  status: string;
  code: number;
  header: Header[];
  body: string;
}

interface Event {
  listen: "prerequest" | "test";
  script: {
    type: "text/javascript";
    exec: string[];
  };
}
```

### Authentication Flow

The collection implements a token-based authentication flow:

1. **Initial Authentication**: User runs a login request (POST /api/auth/login or POST /api/auth/register)
2. **Token Extraction**: Test script extracts `access_token` from response and saves to environment
3. **Automatic Header Injection**: Pre-request scripts on authenticated endpoints add `Authorization: Bearer {{access_token}}` header
4. **Token Reuse**: All subsequent requests use the stored token
5. **Token Refresh**: User re-runs login if token expires

**Pre-Request Script Template (Authenticated Endpoints):**

```javascript
// Set Authorization header with access token
if (pm.environment.get("access_token")) {
    pm.request.headers.add({
        key: "Authorization",
        value: "Bearer " + pm.environment.get("access_token")
    });
}
```

**Test Script Template (Login Endpoints):**

```javascript
// Validate response
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Response has access_token", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("access_token");
    
    // Save token to environment
    pm.environment.set("access_token", jsonData.access_token);
    
    // Save workspace info if present
    if (jsonData.workspace) {
        pm.environment.set("workspace_id", jsonData.workspace.id);
        pm.environment.set("workspace_slug", jsonData.workspace.slug);
    }
});

pm.test("Response has user info", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("user");
    pm.expect(jsonData.user).to.have.property("email");
});
```

### Test Script Patterns

The collection uses consistent test script patterns for different endpoint types:

**Pattern 1: Resource Creation (POST endpoints that create resources)**

```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Response has id field", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("id");
    
    // Save resource ID to environment
    pm.environment.set("resource_id", jsonData.id);
});

pm.test("Content-Type is application/json", function () {
    pm.response.to.have.header("Content-Type");
    pm.expect(pm.response.headers.get("Content-Type")).to.include("application/json");
});
```

**Pattern 2: Resource Retrieval (GET endpoints)**

```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Response has expected structure", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.be.an("object");
    // Add specific field checks
});

pm.test("Content-Type is application/json", function () {
    pm.response.to.have.header("Content-Type");
    pm.expect(pm.response.headers.get("Content-Type")).to.include("application/json");
});
```

**Pattern 3: List Endpoints (GET endpoints with pagination)**

```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Response has pagination fields", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("total_count");
    pm.expect(jsonData).to.have.property("has_more");
});

pm.test("Response has items array", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("items").that.is.an("array");
    
    // Save first item ID if available
    if (jsonData.items.length > 0) {
        pm.environment.set("first_item_id", jsonData.items[0].id);
    }
});
```

**Pattern 4: Success Message (DELETE, status update endpoints)**

```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});

pm.test("Response has success message", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("message");
});
```

**Pattern 5: Health Check Endpoints**

```javascript
pm.test("Status code is 200 or 503", function () {
    pm.expect(pm.response.code).to.be.oneOf([200, 503]);
});

pm.test("Response has status field", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData).to.have.property("status");
});
```

## Data Models

### Collection Root Object

```json
{
  "info": {
    "name": "ChatSaaS Backend API",
    "description": "Comprehensive API collection for ChatSaaS Backend...",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    "version": "1.0.0",
    "_postman_id": "generated-uuid"
  },
  "item": [
    // Folder and request items
  ]
}
```

### Folder Object

```json
{
  "name": "Authentication",
  "description": "Authentication endpoints for user and agent login...",
  "item": [
    // Nested requests
  ]
}
```

### Request Object Example (POST /api/auth/login)

```json
{
  "name": "POST Login",
  "request": {
    "method": "POST",
    "header": [
      {
        "key": "Content-Type",
        "value": "application/json",
        "type": "text"
      }
    ],
    "url": {
      "raw": "{{base_url}}/api/auth/login",
      "host": ["{{base_url}}"],
      "path": ["api", "auth", "login"]
    },
    "body": {
      "mode": "raw",
      "raw": "{\n  \"email\": \"user@example.com\",\n  \"password\": \"securepassword123\"\n}",
      "options": {
        "raw": {
          "language": "json"
        }
      }
    },
    "description": "User login with email and password. Returns JWT access token..."
  },
  "response": [
    {
      "name": "Success Response",
      "originalRequest": { /* ... */ },
      "status": "OK",
      "code": 200,
      "header": [
        {
          "key": "Content-Type",
          "value": "application/json"
        }
      ],
      "body": "{\n  \"access_token\": \"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...\",\n  \"user\": {\n    \"id\": \"uuid\",\n    \"email\": \"user@example.com\",\n    \"is_active\": true\n  },\n  \"workspace\": {\n    \"id\": \"uuid\",\n    \"name\": \"My Business\",\n    \"slug\": \"my-business\",\n    \"tier\": \"free\"\n  }\n}"
    },
    {
      "name": "Invalid Credentials",
      "originalRequest": { /* ... */ },
      "status": "Unauthorized",
      "code": 401,
      "header": [
        {
          "key": "Content-Type",
          "value": "application/json"
        }
      ],
      "body": "{\n  \"detail\": \"Invalid email or password\"\n}"
    }
  ],
  "event": [
    {
      "listen": "test",
      "script": {
        "type": "text/javascript",
        "exec": [
          "pm.test(\"Status code is 200\", function () {",
          "    pm.response.to.have.status(200);",
          "});",
          "",
          "pm.test(\"Response has access_token\", function () {",
          "    var jsonData = pm.response.json();",
          "    pm.expect(jsonData).to.have.property(\"access_token\");",
          "    pm.environment.set(\"access_token\", jsonData.access_token);",
          "    ",
          "    if (jsonData.workspace) {",
          "        pm.environment.set(\"workspace_id\", jsonData.workspace.id);",
          "        pm.environment.set(\"workspace_slug\", jsonData.workspace.slug);",
          "    }",
          "});"
        ]
      }
    }
  ]
}
```

### Request with Path Variables (GET /api/channels/{channel_id})

```json
{
  "name": "GET Channel by ID",
  "request": {
    "method": "GET",
    "header": [],
    "url": {
      "raw": "{{base_url}}/api/channels/:channel_id",
      "host": ["{{base_url}}"],
      "path": ["api", "channels", ":channel_id"],
      "variable": [
        {
          "key": "channel_id",
          "value": "{{channel_id}}",
          "description": "Channel UUID"
        }
      ]
    },
    "description": "Get channel details by ID..."
  },
  "event": [
    {
      "listen": "prerequest",
      "script": {
        "type": "text/javascript",
        "exec": [
          "if (pm.environment.get(\"access_token\")) {",
          "    pm.request.headers.add({",
          "        key: \"Authorization\",",
          "        value: \"Bearer \" + pm.environment.get(\"access_token\")",
          "    });",
          "}"
        ]
      }
    }
  ]
}
```

### Request with Query Parameters (GET /api/documents)

```json
{
  "name": "GET List Documents",
  "request": {
    "method": "GET",
    "header": [],
    "url": {
      "raw": "{{base_url}}/api/documents?status_filter=completed&limit=50&offset=0",
      "host": ["{{base_url}}"],
      "path": ["api", "documents"],
      "query": [
        {
          "key": "status_filter",
          "value": "completed",
          "description": "Filter by status (pending, processing, completed, failed)",
          "disabled": true
        },
        {
          "key": "limit",
          "value": "50",
          "description": "Maximum number of documents (default: 50, max: 100)"
        },
        {
          "key": "offset",
          "value": "0",
          "description": "Offset for pagination (default: 0)"
        }
      ]
    },
    "description": "List documents for the workspace with optional filtering and pagination..."
  }
}
```

### Multipart Form Data Request (POST /api/documents/upload)

```json
{
  "name": "POST Upload Document",
  "request": {
    "method": "POST",
    "header": [],
    "url": {
      "raw": "{{base_url}}/api/documents/upload",
      "host": ["{{base_url}}"],
      "path": ["api", "documents", "upload"]
    },
    "body": {
      "mode": "formdata",
      "formdata": [
        {
          "key": "file",
          "type": "file",
          "src": [],
          "description": "Document file (PDF or TXT, max 10MB)"
        },
        {
          "key": "name",
          "value": "My Document",
          "type": "text",
          "description": "Optional custom document name",
          "disabled": true
        }
      ]
    },
    "description": "Upload and process a document for the workspace..."
  },
  "event": [
    {
      "listen": "prerequest",
      "script": {
        "type": "text/javascript",
        "exec": [
          "if (pm.environment.get(\"access_token\")) {",
          "    pm.request.headers.add({",
          "        key: \"Authorization\",",
          "        value: \"Bearer \" + pm.environment.get(\"access_token\")",
          "    });",
          "}"
        ]
      }
    },
    {
      "listen": "test",
      "script": {
        "type": "text/javascript",
        "exec": [
          "pm.test(\"Status code is 200\", function () {",
          "    pm.response.to.have.status(200);",
          "});",
          "",
          "pm.test(\"Response has document_id\", function () {",
          "    var jsonData = pm.response.json();",
          "    pm.expect(jsonData).to.have.property(\"id\");",
          "    pm.environment.set(\"document_id\", jsonData.id);",
          "});"
        ]
      }
    }
  ]
}
```

### WebSocket Documentation Request

Since Postman has limited WebSocket support, we document WebSocket connections as a descriptive request:

```json
{
  "name": "WebSocket Connection Documentation",
  "request": {
    "method": "GET",
    "header": [],
    "url": {
      "raw": "ws://{{base_url}}/ws/:workspace_id?token={{access_token}}",
      "protocol": "ws",
      "host": ["{{base_url}}"],
      "path": ["ws", ":workspace_id"],
      "query": [
        {
          "key": "token",
          "value": "{{access_token}}",
          "description": "JWT authentication token"
        }
      ],
      "variable": [
        {
          "key": "workspace_id",
          "value": "{{workspace_id}}",
          "description": "Workspace UUID"
        }
      ]
    },
    "description": "# WebSocket Connection\n\n**URL Format:** `ws://your-domain/ws/{workspace_id}?token=<jwt_token>`\n\n## Client → Server Messages\n\n### Ping\n```json\n{\n  \"type\": \"ping\"\n}\n```\n\n### Subscribe to Events\n```json\n{\n  \"type\": \"subscribe\",\n  \"events\": [\"escalation\", \"new_message\", \"agent_claim\"]\n}\n```\n\n### Get Statistics\n```json\n{\n  \"type\": \"get_stats\"\n}\n```\n\n### Get Conversations\n```json\n{\n  \"type\": \"get_conversations\",\n  \"status\": \"escalated\",\n  \"limit\": 20,\n  \"offset\": 0\n}\n```\n\n### Get Agents\n```json\n{\n  \"type\": \"get_agents\"\n}\n```\n\n## Server → Client Messages\n\n### Pong\n```json\n{\n  \"type\": \"pong\",\n  \"timestamp\": \"2024-01-01T00:00:00Z\"\n}\n```\n\n### Subscription Confirmed\n```json\n{\n  \"type\": \"subscription_confirmed\",\n  \"subscribed_events\": [\"escalation\", \"new_message\"],\n  \"available_events\": [\"escalation\", \"agent_claim\", \"new_message\", \"conversation_status_change\", \"agent_status_change\", \"document_processing\", \"system_notification\"]\n}\n```\n\n### Escalation Event\n```json\n{\n  \"type\": \"escalation\",\n  \"conversation_id\": \"uuid\",\n  \"escalation_reason\": \"customer_request\",\n  \"timestamp\": \"2024-01-01T00:00:00Z\"\n}\n```\n\n### Agent Claim Event\n```json\n{\n  \"type\": \"agent_claim\",\n  \"conversation_id\": \"uuid\",\n  \"agent_id\": \"uuid\",\n  \"agent_name\": \"John Doe\",\n  \"timestamp\": \"2024-01-01T00:00:00Z\"\n}\n```\n\n### New Message Event\n```json\n{\n  \"type\": \"new_message\",\n  \"conversation_id\": \"uuid\",\n  \"message_id\": \"uuid\",\n  \"timestamp\": \"2024-01-01T00:00:00Z\"\n}\n```\n\n### Conversation Status Change\n```json\n{\n  \"type\": \"conversation_status_change\",\n  \"conversation_id\": \"uuid\",\n  \"old_status\": \"escalated\",\n  \"new_status\": \"agent\",\n  \"agent_id\": \"uuid\",\n  \"timestamp\": \"2024-01-01T00:00:00Z\"\n}\n```\n\n### Error\n```json\n{\n  \"type\": \"error\",\n  \"message\": \"Error description\"\n}\n```\n\n**Note:** Postman has limited WebSocket support. Use a dedicated WebSocket client for testing WebSocket connections."
  }
}
```

### Collection Description Template

The collection-level description provides essential information for users:

```markdown
# ChatSaaS Backend API

Complete API collection for the ChatSaaS Backend platform. This collection includes all REST endpoints, WebSocket documentation, and webhook integrations.

## Version

API Version: 1.0  
Collection Version: 1.0.0  
Last Updated: 2024-01-01

## Getting Started

### 1. Set Up Environment Variables

Before using this collection, create a Postman environment with the following variables:

- `base_url`: API base URL (default: `http://localhost:8000`)
- `access_token`: JWT authentication token (auto-populated by login requests)
- `workspace_id`: Current workspace ID (auto-populated)
- `workspace_slug`: Current workspace slug (auto-populated)
- `channel_id`: Current channel ID (auto-populated)
- `document_id`: Current document ID (auto-populated)
- `agent_id`: Current agent ID (auto-populated)
- `conversation_id`: Current conversation ID (auto-populated)
- `session_token`: WebChat session token (auto-populated)
- `widget_id`: WebChat widget ID (auto-populated)
- `invitation_token`: Agent invitation token (auto-populated)

### 2. Authenticate

Run one of the authentication requests to obtain an access token:

- **POST Register**: Create a new user account and workspace
- **POST Login**: Login with existing credentials
- **POST Agent Login**: Login as an agent

The test scripts will automatically save the `access_token` to your environment.

### 3. Use the Collection

All authenticated endpoints will automatically use the stored `access_token`. Navigate through the folders to explore different API areas.

## Authentication

Most endpoints require JWT authentication via Bearer token. The collection automatically adds the Authorization header using pre-request scripts.

**Token Format:** `Authorization: Bearer <access_token>`

Tokens contain:
- User ID and email
- User role (owner, agent)
- Workspace ID
- Expiration timestamp

## Tier Limits

Different tiers have different limits:

| Feature | Free | Starter | Growth | Pro |
|---------|------|---------|--------|-----|
| Channels | 3 | 10 | 25 | Unlimited |
| Agents | 5 | 15 | 50 | Unlimited |
| Documents | 10 | 50 | 200 | Unlimited |
| Messages/month | 1000 | 10000 | 50000 | Unlimited |

Exceeding limits returns 402 Payment Required error.

## Rate Limiting

Rate limits are enforced on public endpoints:

- **WebChat /send**: 10 messages per minute per session
- **WebChat /messages**: 30 requests per minute per session

Rate limit headers:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Unix timestamp when limit resets

## Error Responses

All endpoints follow a consistent error response format:

```json
{
  "detail": "Error description"
}
```

Common status codes:
- `400`: Bad Request - Invalid parameters
- `401`: Unauthorized - Missing or invalid authentication
- `402`: Payment Required - Tier limit exceeded
- `403`: Forbidden - Insufficient permissions
- `404`: Not Found - Resource not found
- `413`: Request Entity Too Large - File size exceeded
- `429`: Too Many Requests - Rate limit exceeded
- `500`: Internal Server Error
- `503`: Service Unavailable

## WebSocket Connections

WebSocket connections require JWT authentication via query parameter:

```
ws://your-domain/ws/{workspace_id}?token=<jwt_token>
```

See the WebSocket folder for detailed message format documentation.

## Documentation

For complete API documentation, see: [API_DOCUMENTATION.md](../API_DOCUMENTATION.md)

## Support

For API support and questions, contact the platform administrator.
```



## Error Handling

### Collection-Level Error Handling

The collection does not implement collection-level error handling. Instead, error handling is implemented at the request level through test scripts and example responses.

### Request-Level Error Handling

Each request includes:

1. **Example Error Responses**: Multiple response examples showing different error scenarios
2. **Test Scripts**: Validate expected status codes and error response structure
3. **Descriptive Messages**: Clear descriptions of when errors occur and how to resolve them

### Error Response Examples

Each request that can return errors includes example responses for:

- **400 Bad Request**: Invalid request parameters, validation failures
- **401 Unauthorized**: Missing or invalid authentication token
- **402 Payment Required**: Tier limit exceeded
- **403 Forbidden**: Insufficient permissions for the operation
- **404 Not Found**: Resource not found
- **413 Request Entity Too Large**: File size exceeds limit (document upload)
- **429 Too Many Requests**: Rate limit exceeded (WebChat endpoints)
- **500 Internal Server Error**: Unexpected server error
- **503 Service Unavailable**: Service temporarily unavailable (health checks)

### Error Response Structure

All error responses follow a consistent structure:

```json
{
  "detail": "Human-readable error message"
}
```

### Test Script Error Validation

Test scripts validate error responses when appropriate:

```javascript
// For endpoints that may return 402 on tier limit
pm.test("Status code is 200 or 402", function () {
    pm.expect(pm.response.code).to.be.oneOf([200, 402]);
});

if (pm.response.code === 402) {
    pm.test("Tier limit error has detail", function () {
        var jsonData = pm.response.json();
        pm.expect(jsonData).to.have.property("detail");
        pm.expect(jsonData.detail).to.include("Tier limit");
    });
}
```

### Webhook Signature Verification Errors

Webhook endpoints document signature verification in their descriptions:

- **Telegram**: Uses bot_token in URL path for identification (no signature verification)
- **WhatsApp/Instagram**: Verifies `X-Hub-Signature-256` header using HMAC-SHA256
- Invalid signatures result in 401 Unauthorized responses

### Rate Limit Error Handling

WebChat endpoints that enforce rate limits include:

1. **429 Response Example**: Shows rate limit exceeded error
2. **Header Documentation**: Documents rate limit headers in response examples
3. **Retry Guidance**: Describes when to retry based on `X-RateLimit-Reset` header

### Authentication Error Handling

Authentication-related errors are handled through:

1. **Pre-Request Script Checks**: Verify `access_token` exists before making authenticated requests
2. **401 Response Examples**: Show invalid credentials and expired token errors
3. **Token Refresh Guidance**: Collection description explains how to refresh tokens

### File Upload Error Handling

Document upload endpoint includes specific error handling for:

- **No file provided**: 400 error with descriptive message
- **Unsupported file type**: 400 error specifying supported types (PDF, TXT)
- **File too large**: 413 error with size limit information
- **Tier limit exceeded**: 402 error indicating document limit reached

### Validation Error Handling

Endpoints with complex validation (channel creation, agent invitation) include:

1. **Validation Failure Examples**: Show specific validation error messages
2. **Field-Level Errors**: Document which fields are required and their constraints
3. **Credential Validation**: Separate validation endpoints to test credentials before creation

## Testing Strategy

### Overview

The Postman collection serves as both documentation and a testing tool. Testing is performed manually by users running requests in Postman, with automated validation provided by test scripts.

### Test Script Coverage

Test scripts are included for all endpoints and follow consistent patterns based on endpoint type:

1. **Authentication Endpoints**: Validate token extraction and storage
2. **Resource Creation**: Validate response structure and save resource IDs
3. **Resource Retrieval**: Validate response structure and data types
4. **List Endpoints**: Validate pagination fields and array structure
5. **Update/Delete Endpoints**: Validate success messages
6. **Health Check Endpoints**: Validate status codes and health indicators

### Manual Testing Workflow

Users perform manual testing by:

1. **Setting Up Environment**: Create Postman environment with `base_url` variable
2. **Running Authentication**: Execute login request to obtain access token
3. **Testing Endpoints**: Navigate through folders and run requests
4. **Reviewing Test Results**: Check test script results in Postman Test Results tab
5. **Inspecting Responses**: Review response bodies and headers
6. **Testing Error Cases**: Modify requests to trigger error conditions

### Automated Validation

Test scripts provide automated validation for:

- **Status Codes**: Verify expected HTTP status codes
- **Response Structure**: Validate presence of required fields
- **Data Types**: Check field types (strings, numbers, booleans, arrays, objects)
- **Content-Type Headers**: Verify JSON content type for JSON endpoints
- **Variable Extraction**: Automatically save IDs and tokens for subsequent requests

### Request Chaining

The collection supports request chaining through environment variables:

1. **POST Register/Login** → Saves `access_token`, `workspace_id`, `workspace_slug`
2. **POST Create Channel** → Saves `channel_id`, `widget_id`
3. **POST Upload Document** → Saves `document_id`
4. **POST Invite Agent** → Saves `agent_id`, `invitation_token`
5. **GET List Conversations** → Saves first `conversation_id`
6. **POST WebChat Send** → Saves `session_token`

This enables testing complete workflows:

- **User Registration → Channel Creation → Document Upload**
- **Login → Agent Invitation → Agent Acceptance**
- **Login → Conversation Listing → Conversation Claim → Send Message**

### Example Response Testing

Each request includes multiple example responses:

- **Success Response (200)**: Shows expected successful response
- **Error Responses**: Show various error scenarios (400, 401, 403, 404, 402, 429, etc.)

Users can compare actual responses against examples to verify correct behavior.

### Environment-Specific Testing

The collection supports testing across multiple environments:

1. **Development**: `base_url = http://localhost:8000`
2. **Staging**: `base_url = https://staging.example.com`
3. **Production**: `base_url = https://api.example.com`

Users create separate Postman environments for each, enabling easy switching.

### Pagination Testing

List endpoints with pagination include:

- **Query Parameters**: Pre-configured with default values (limit=50, offset=0)
- **Disabled Parameters**: Optional filters are disabled by default, users enable as needed
- **Test Scripts**: Validate `total_count` and `has_more` fields
- **Documentation**: Describe default values and maximum limits

### Multipart Form Data Testing

Document upload endpoint uses multipart/form-data:

- **File Parameter**: Users select file from their system
- **Optional Parameters**: Name parameter is disabled by default
- **Size Validation**: Description warns about 10MB limit
- **Type Validation**: Description specifies supported types (PDF, TXT)

### WebSocket Testing Limitations

WebSocket connections cannot be fully tested in Postman:

- **Documentation Only**: WebSocket folder provides message format documentation
- **REST Endpoints**: WebSocket management endpoints (health, connections, broadcast) are testable
- **External Tools**: Users must use dedicated WebSocket clients for connection testing

### Webhook Testing

Webhook endpoints are challenging to test directly:

- **Test Endpoint**: POST /webhooks/test/{channel_type} allows authenticated testing
- **Signature Verification**: Documented but not easily testable in Postman
- **Platform Integration**: Real webhook testing requires platform configuration (Telegram, WhatsApp, Instagram)

### Admin Endpoint Testing

Platform administration endpoints require super admin role:

- **Role Requirement**: Documented in folder description
- **403 Errors**: Non-admin users receive Forbidden errors
- **Separate Environment**: Admins may use separate environment with admin credentials

### Test Script Maintenance

Test scripts are designed to be:

- **Consistent**: Use same patterns across similar endpoints
- **Maintainable**: Simple, readable JavaScript code
- **Extensible**: Easy to add additional validations
- **Documented**: Include comments explaining validation logic

### Validation Scope

Test scripts validate:

- **Response Status**: HTTP status codes
- **Response Structure**: Presence of required fields
- **Data Types**: Field type validation
- **Environment Variables**: Automatic extraction and storage
- **Content-Type**: Header validation

Test scripts do NOT validate:

- **Business Logic**: Actual data values and relationships
- **Database State**: Persistence and data integrity
- **Performance**: Response times and throughput
- **Security**: Authentication strength and authorization logic
- **Concurrent Access**: Race conditions and locking

These aspects require separate testing approaches beyond the Postman collection.



## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

### Property Reflection

After analyzing all acceptance criteria, I identified several areas where properties could be consolidated:

1. **Resource Creation Test Scripts**: Requirements 2.6, 3.8, 4.7, 5.11, 6.8, and 8.5 all specify that resource creation endpoints should extract IDs and save them to environment variables. These can be combined into a single property about resource creation endpoints.

2. **Test Script Validation**: Requirements 13.1, 13.2, 13.3, 13.4, and 13.5 all specify different aspects of test script validation. While they test different things, they all relate to test script presence and correctness.

3. **Error Response Examples**: Requirements 14.3 and 17.2 both specify that error response examples should be included. These are redundant.

4. **Query Parameter Properties**: Requirements 20.1, 20.2, 20.3, 20.4, and 20.5 all relate to query parameters and can be consolidated into fewer properties.

5. **Documentation Properties**: Requirements 7.8, 17.3, and 17.4 all relate to documentation in descriptions and can be consolidated.

The following properties represent the unique, non-redundant validation requirements:

### Property 1: Request Naming Convention

For any request in the collection, the request name should follow the format "{HTTP_METHOD} {endpoint_name}" where HTTP_METHOD is the HTTP method (GET, POST, PUT, DELETE) and endpoint_name is a descriptive name.

**Validates: Requirements 1.3**

### Property 2: Request Organization

For any request in the collection, the request should be placed in a folder that corresponds to its API functional area based on the URL path structure.

**Validates: Requirements 1.2**

### Property 3: Base URL Variable Usage

For any request in the collection, the request URL should use the {{base_url}} environment variable as the host component.

**Validates: Requirements 11.3**

### Property 4: Authentication Header for Authenticated Endpoints

For any request that requires authentication (non-public endpoints), the request should either have an Authorization header with value "Bearer {{access_token}}" or a pre-request script that adds this header.

**Validates: Requirements 11.4, 12.1**

### Property 5: No Authentication for Public Endpoints

For any public endpoint (webhooks, WebChat public API, health checks), the request should not include authentication headers or pre-request scripts that add authentication.

**Validates: Requirements 12.3**

### Property 6: Environment Variable Usage in Path Parameters

For any request with path variables (e.g., {channel_id}, {document_id}), the path variable should reference an environment variable (e.g., {{channel_id}}, {{document_id}}).

**Validates: Requirements 11.5**

### Property 7: Resource Creation Test Scripts

For any request that creates a resource (POST endpoints that return an id field), the request should include a test script that extracts the id from the response and saves it to an appropriate environment variable.

**Validates: Requirements 2.6, 3.8, 4.7, 5.11, 8.5**

### Property 8: List Endpoint Test Scripts

For any request that returns a paginated list (endpoints with limit and offset parameters), the request should include a test script that validates the presence of pagination fields (total_count, has_more) and optionally extracts the first item's id.

**Validates: Requirements 6.8, 20.4**

### Property 9: Status Code Validation in Test Scripts

For any request in the collection, the request should include a test script that validates the response status code is the expected success code (typically 200).

**Validates: Requirements 13.1**

### Property 10: Response Structure Validation in Test Scripts

For any request in the collection, the request should include a test script that validates the response has expected fields based on the API documentation.

**Validates: Requirements 13.2, 13.4**

### Property 11: Content-Type Validation for JSON Endpoints

For any request that expects a JSON response, the request should include a test script that validates the Content-Type header is application/json.

**Validates: Requirements 13.3**

### Property 12: Request Body for POST and PUT Endpoints

For any POST or PUT request in the collection, the request should include a request body with example data matching the API documentation.

**Validates: Requirements 14.1**

### Property 13: Success Response Examples

For any request in the collection, the request should include at least one example response showing a successful (200 status) response with example data.

**Validates: Requirements 14.2**

### Property 14: Error Response Examples

For any request that can return error responses (400, 401, 403, 404, 402, 413, 429, 500, 503), the request should include example responses for the documented error cases.

**Validates: Requirements 14.3, 17.2**

### Property 15: Request Descriptions

For any request in the collection, the request should include a description field that explains the endpoint purpose and parameters.

**Validates: Requirements 14.4**

### Property 16: Parameter Descriptions

For any request with path variables or query parameters, each parameter should include a description field explaining its purpose and constraints.

**Validates: Requirements 14.5, 20.3**

### Property 17: Pagination Query Parameters

For any request that supports pagination, the request should include limit and offset query parameters with example values.

**Validates: Requirements 20.1**

### Property 18: Filter Query Parameters

For any request that supports filtering (status, tier, active_only, etc.), the request should include the appropriate query parameters as documented in the API.

**Validates: Requirements 20.2**

### Property 19: Query Parameter Format

For any request with query parameters, the parameters should use Postman's query parameter format with key-value pairs, and optional parameters should have a disabled state.

**Validates: Requirements 20.5**

### Property 20: Collection Schema Compliance

The collection JSON structure should conform to the Postman Collection Format v2.1 schema, including all required fields and proper nesting of folders and requests.

**Validates: Requirements 18.1, 18.3, 18.4**

### Property 21: JSON Formatting

The collection JSON file should be formatted with consistent indentation (2 or 4 spaces) for readability.

**Validates: Requirements 19.4**

### Property 22: Endpoint-Specific Documentation

For any endpoint with special requirements (webhook signature verification, rate limits, tier limits), the request description should document these requirements.

**Validates: Requirements 7.8, 17.3, 17.4**

### Property 23: Health Endpoint Test Scripts

For any health check endpoint, the request should include a test script that validates the response status code is either 200 (healthy) or 503 (unhealthy).

**Validates: Requirements 10.6**

### Example-Based Validation

The following requirements are validated through specific examples rather than universal properties:

- **Requirement 1.1**: Collection has folders for Authentication, Channel Management, Document Management, Agent Management, Conversation Management, Webhooks, WebSocket, WebChat Public API, Platform Administration, and Metrics & Monitoring
- **Requirements 2.1-2.5**: Authentication endpoints (POST Register, POST Login, POST Agent Login, POST Accept Invite, GET Me) exist with correct structure
- **Requirements 3.1-3.7**: Channel management endpoints exist with correct structure
- **Requirements 4.1-4.6**: Document management endpoints exist with correct structure
- **Requirements 5.1-5.10**: Agent management endpoints exist with correct structure
- **Requirements 6.1-6.7**: Conversation management endpoints exist with correct structure
- **Requirements 7.1-7.7**: Webhook endpoints exist with correct structure
- **Requirements 8.1-8.4**: WebChat public API endpoints exist with correct structure
- **Requirements 9.1-9.10**: Platform administration endpoints exist with correct structure
- **Requirements 10.1-10.5**: Metrics and monitoring endpoints exist with correct structure
- **Requirements 15.1-15.6**: WebSocket folder and documentation exist with correct structure
- **Requirements 16.1-16.6**: Collection metadata (name, description, version, documentation links) is correct
- **Requirements 17.1**: Collection description documents error response format
- **Requirements 18.2**: Collection has required top-level fields (info, item)
- **Requirements 19.1-19.3**: Collection file name, location, and version information are correct

These example-based validations will be tested through unit tests that check for the presence and structure of specific endpoints and documentation.

