# ChatSaaS Backend API - Postman Collection

This directory contains a comprehensive Postman Collection v2.1 for the ChatSaaS Backend API.

## File

- `ChatSaaS_Backend_API.postman_collection.json` - Complete API collection with 52 endpoints across 10 functional areas

## Collection Contents

The collection includes all REST API endpoints organized into the following folders:

1. **Authentication** (5 endpoints) - User and agent login, registration, token management
2. **Channel Management** (10 endpoints) - Create and manage Telegram, WhatsApp, Instagram, and WebChat channels
3. **Document Management** (6 endpoints) - Upload, process, and manage knowledge base documents
4. **Agent Management** (6 endpoints) - Invite, manage, and monitor human agents
5. **Conversation Management** (6 endpoints) - View, claim, and manage customer conversations
6. **Webhooks** (3 endpoints) - Receive events from external platforms
7. **WebSocket** (4 endpoints) - Real-time connection documentation, management, and broadcasting
8. **WebChat Public API** (3 endpoints) - Public widget integration endpoints
9. **Platform Administration** (5 endpoints) - Manage users, workspaces, and system settings
10. **Metrics & Monitoring** (5 endpoints) - Health checks, system metrics, and alerting

## Features

- ✅ **Complete Coverage**: All 53 API endpoints with proper request structure
- ✅ **Authentication**: Automatic JWT token management via pre-request scripts
- ✅ **Test Scripts**: Response validation and automatic variable extraction
- ✅ **Environment Variables**: Support for multiple environments (dev, staging, production)
- ✅ **Example Requests**: Pre-filled request bodies for all POST/PUT endpoints
- ✅ **Documentation**: Comprehensive descriptions for all endpoints and parameters
- ✅ **Request Chaining**: Automatic ID extraction for seamless workflow testing
- ✅ **WebSocket Support**: Complete WebSocket message documentation and REST management endpoints

## 🚀 Quick Start with Postman

### ✨ Zero Configuration - Just Import and Go!

Everything is pre-configured! No manual setup needed.

**Step 1: Import Files**
1. Open Postman
2. Click **Import** → Select both files:
   - `ChatSaaS_Backend_API.postman_collection.json`
   - `ChatSaaS_Local.postman_environment.json`
3. Click **Import**

**Step 2: Select Environment**
- Select **"ChatSaaS Local"** from environment dropdown (top right)

**Step 3: Login**
1. Open **Authentication** folder → **POST Login**
2. Click **Send**
3. ✅ Token automatically saved! All requests now work!

### 🎯 What's Pre-Configured

- ✅ **Base URL**: `http://localhost:8000` (collection-level variable)
- ✅ **Authentication**: Automatic Bearer token for all requests
- ✅ **Token Management**: Auto-saves and auto-checks expiration
- ✅ **All Variables**: Auto-populated as you test (workspace_id, channel_id, etc.)
- ✅ **Response Logging**: Automatic response time and status logging

### 💡 Test Credentials

```json
{
  "email": "testuser@example.com",
  "password": "securepassword123"
}
```

No manual configuration needed - everything works out of the box!

## Example Workflows

### Complete User Workflow

1. **POST Register** → Creates user and workspace, saves `access_token` and `workspace_id`
2. **POST Create Channel - Telegram** → Creates channel, saves `channel_id`
3. **POST Upload Document** → Uploads document, saves `document_id`
4. **POST Invite Agent** → Invites agent, saves `agent_id` and `invitation_token`
5. **GET List Conversations** → Lists conversations
6. **POST Claim Conversation** → Claims a conversation
7. **POST Send Message** → Sends message as agent

### WebChat Testing Workflow

1. **POST Register** → Get workspace
2. **POST Create Channel - WebChat** → Creates WebChat channel, saves `widget_id`
3. **GET Widget Config** → Get widget configuration
4. **POST Send Message** → Send message, saves `session_token`
5. **GET Messages** → Retrieve conversation messages

## Environment Configuration

### Development
```
base_url = http://localhost:8000
```

### Staging
```
base_url = https://staging-api.example.com
```

### Production
```
base_url = https://api.example.com
```

## Test Scripts

The collection includes automated test scripts that:

- ✅ Validate response status codes
- ✅ Check response structure and required fields
- ✅ Verify Content-Type headers
- ✅ Extract and save resource IDs to environment variables
- ✅ Enable request chaining for complete workflow testing

## Rate Limits

Be aware of rate limits on public endpoints:

- **WebChat /send**: 10 messages per minute per session
- **WebChat /messages**: 30 requests per minute per session

## Tier Limits

Different workspace tiers have different limits:

| Feature | Free | Starter | Growth | Pro |
|---------|------|---------|--------|-----|
| Channels | 3 | 10 | 25 | Unlimited |
| Agents | 5 | 15 | 50 | Unlimited |
| Documents | 10 | 50 | 200 | Unlimited |
| Messages/month | 1000 | 10000 | 50000 | Unlimited |

Exceeding limits returns `402 Payment Required` error.

## Error Responses

All endpoints follow a consistent error response format:

```json
{
  "detail": "Error description"
}
```

Common status codes:
- `400` - Bad Request (invalid parameters)
- `401` - Unauthorized (missing/invalid authentication)
- `402` - Payment Required (tier limit exceeded)
- `403` - Forbidden (insufficient permissions)
- `404` - Not Found (resource not found)
- `413` - Request Entity Too Large (file size exceeded)
- `429` - Too Many Requests (rate limit exceeded)
- `500` - Internal Server Error
- `503` - Service Unavailable

## WebSocket Testing

The WebSocket folder includes comprehensive documentation and management endpoints:

### WebSocket Connection Documentation
Complete reference for all WebSocket message types:
- **Client → Server**: ping, subscribe, get_stats, get_conversations, get_agents
- **Server → Client**: pong, subscription_confirmed, escalation, agent_claim, new_message, conversation_status_change, error
- **Available Events**: escalation, agent_claim, new_message, conversation_status_change, agent_status_change, document_processing, system_notification

### REST Management Endpoints (Testable in Postman)
- **GET WebSocket Health** - Health check endpoint
- **GET Workspace Connections** - List active WebSocket connections
- **POST Broadcast Message** - Send messages to all connected clients in a workspace

### Testing WebSocket Connections
For actual WebSocket connection testing, use dedicated tools:
- **wscat** CLI: `wscat -c "ws://localhost:8000/ws/{workspace_id}?token={jwt_token}"`
- **Browser DevTools** with JavaScript WebSocket API
- **Postman WebSocket Request** (beta feature)
- **Dedicated clients** like Insomnia or Hoppscotch

WebSocket URL format:
```
ws://your-domain/ws/{workspace_id}?token=<jwt_token>
```

## Webhook Testing

Webhook endpoints are designed to receive events from external platforms (Telegram, WhatsApp, Instagram). For testing:

- Use the **POST Test Webhook** endpoint (requires authentication)
- Or configure actual platform webhooks pointing to your API

## Admin Endpoints

Platform Administration endpoints require **super admin role**. Regular users will receive `403 Forbidden` errors.

## Support

For complete API documentation, see: [API_DOCUMENTATION.md](./API_DOCUMENTATION.md)

## Collection Metadata

- **Format**: Postman Collection v2.1
- **Version**: 1.0.0
- **Total Endpoints**: 53
- **Total Folders**: 10
- **File Size**: ~105KB
- **Last Updated**: 2026-03-19

## Troubleshooting

### "access_token not found" errors

Make sure you've run a login request first (POST Register, POST Login, or POST Agent Login) to obtain and save the access token.

### Path variable errors

Ensure you've run the prerequisite requests that save the required IDs (e.g., run POST Create Channel before GET Channel by ID).

### 402 Payment Required errors

You've exceeded your workspace tier limits. Upgrade your tier or delete some resources.

### 429 Rate Limit errors

You've exceeded rate limits on WebChat endpoints. Wait for the rate limit window to reset (check `X-RateLimit-Reset` header).

## Contributing

To update the collection:

1. Make changes in Postman
2. Export the collection (Collection v2.1 format)
3. Replace `ChatSaaS_Backend_API.postman_collection.json`
4. Update this README if needed

## License

This collection is part of the ChatSaaS Backend project.
