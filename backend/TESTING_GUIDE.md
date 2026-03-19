# Testing Guide - Postman Collection

## ✅ Backend Server Status

The backend server is currently running at: **http://localhost:8000**

## 🚀 Quick Start with Postman

### Step 1: Import the Collection

1. Open Postman
2. Click **Import** button (top left)
3. Select **File** tab
4. Choose `backend/ChatSaaS_Backend_API.postman_collection.json`
5. Click **Import**

### Step 2: Create Environment

1. Click **Environments** in the left sidebar
2. Click **+** to create new environment
3. Name it: `ChatSaaS Local`
4. Add this variable:
   - Variable: `base_url`
   - Initial Value: `http://localhost:8000`
   - Current Value: `http://localhost:8000`
5. Click **Save**
6. Select `ChatSaaS Local` from the environment dropdown (top right)

### Step 3: Test Authentication

1. Open the **Authentication** folder in the collection
2. Click **POST Register** request
3. Click **Send**
4. ✅ You should see a response with `access_token`, `user`, and `workspace` data
5. The test script will automatically save the token to your environment!

**Note:** If you get an error that the email already exists, use **POST Login** instead with the same credentials.

### Step 4: Test Other Endpoints

Now that you have an access token, you can test any authenticated endpoint:

1. **Channel Management**
   - Try **POST Create Channel - WebChat** to create a chat widget
   - Try **GET List Channels** to see your channels

2. **Document Management**
   - Try **GET List Documents** to see uploaded documents
   - Try **POST Upload Document** to upload a PDF or TXT file

3. **Conversation Management**
   - Try **GET Conversation Stats** to see conversation statistics

4. **WebSocket**
   - Try **GET WebSocket Health** to check WebSocket service status

5. **Metrics & Monitoring**
   - Try **GET Detailed Health** to see system health

## 🧪 Test Results from CLI

Here's what we tested successfully:

```
✅ Health Check: Working
✅ Authentication: Working (Register/Login)
✅ Authenticated Endpoints: Working
✅ Channel Management: Working
✅ Document Management: Working
✅ Conversation Stats: Working
✅ WebSocket Health: Working
```

## 📊 Collection Overview

- **Total Endpoints**: 53
- **Total Folders**: 10
- **Authentication**: Automatic via pre-request scripts
- **Test Scripts**: Automatic token and ID extraction

## 🔑 Test Credentials

Use these credentials for testing:

```json
{
  "email": "testuser@example.com",
  "password": "securepassword123",
  "business_name": "Test Business"
}
```

**Workspace Created:**
- Name: Test Business
- Slug: test-business
- Tier: free
- ID: 74d4b725-3e20-4b7e-96b5-35296bd7f208

## 📝 Environment Variables

After running authentication requests, these variables will be auto-populated:

- ✅ `access_token` - JWT authentication token
- ✅ `workspace_id` - Your workspace UUID
- ✅ `workspace_slug` - Your workspace slug

Additional variables that get populated as you test:
- `channel_id` - After creating a channel
- `widget_id` - After creating a WebChat channel
- `document_id` - After uploading a document
- `agent_id` - After inviting an agent
- `conversation_id` - After listing conversations
- `session_token` - After sending a WebChat message

## 🎯 Recommended Testing Flow

### Basic Flow
1. **POST Register** or **POST Login** → Get access token
2. **GET Me** → Verify authentication
3. **POST Create Channel - WebChat** → Create a chat widget
4. **GET List Channels** → See your channels
5. **GET Conversation Stats** → Check statistics

### Advanced Flow
1. Complete Basic Flow above
2. **POST Upload Document** → Upload a knowledge base document
3. **GET List Documents** → See processing status
4. **POST Invite Agent** → Invite a human agent
5. **GET List Agents** → See agent status
6. **GET List Conversations** → See customer conversations

### Admin Flow (Requires Super Admin)
1. **GET Overview** → Platform statistics
2. **GET Workspaces** → List all workspaces
3. **GET Users** → List all users
4. **GET Analytics** → Platform analytics

## 🐛 Troubleshooting

### "access_token not found" error
- Make sure you ran **POST Register** or **POST Login** first
- Check that the test script ran successfully (green checkmarks in Tests tab)
- Verify the `access_token` variable is set in your environment

### 401 Unauthorized errors
- Your token may have expired (expires in 7 days)
- Run **POST Login** again to get a new token

### 402 Payment Required errors
- You've hit tier limits (Free tier: 3 channels, 5 agents, 10 documents)
- Delete some resources or upgrade tier (requires admin)

### Connection refused errors
- Make sure the backend server is running: `python3 main.py` in the backend directory
- Check that it's running on port 8000

## 📚 Additional Resources

- **API Documentation**: http://localhost:8000/docs (Swagger UI)
- **ReDoc**: http://localhost:8000/redoc
- **Collection README**: `backend/POSTMAN_COLLECTION_README.md`
- **API Documentation**: `backend/API_DOCUMENTATION.md`

## 🎉 Happy Testing!

You now have a complete Postman collection with 53 endpoints ready to test. All authentication is handled automatically, and test scripts will extract IDs for you to chain requests together.

Enjoy exploring the ChatSaaS Backend API! 🚀
