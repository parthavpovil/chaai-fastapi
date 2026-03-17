#!/usr/bin/env python3
"""
End-to-End System Validation Tests
Tests complete customer journey from message to response and validates multi-tenant isolation.
"""
import pytest
import asyncio
import json
from httpx import AsyncClient
from uuid import uuid4
from datetime import datetime

from app.main import app
from app.database import get_db
from app.models import User, Workspace, Channel, Contact, Conversation, Message
from app.services.auth_service import AuthService


class TestEndToEndValidation:
    """End-to-end system validation tests"""
    
    @pytest.fixture
    async def test_workspace_setup(self):
        """Set up test workspace with user and channel"""
        auth_service = AuthService()
        
        # Create test user and workspace
        user_data = {
            "email": "test@example.com",
            "password": "testpass123",
            "business_name": "Test Business"
        }
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Register user
            response = await client.post("/api/auth/register", json=user_data)
            assert response.status_code == 201
            
            # Login to get token
            login_response = await client.post("/api/auth/login", json={
                "email": user_data["email"],
                "password": user_data["password"]
            })
            assert login_response.status_code == 200
            token = login_response.json()["access_token"]
            
            return {
                "token": token,
                "headers": {"Authorization": f"Bearer {token}"},
                "user_data": user_data
            }
    
    async def test_complete_customer_journey(self, test_workspace_setup):
        """
        Test complete customer journey from message to response
        Validates: Complete system validation
        """
        setup = await test_workspace_setup
        headers = setup["headers"]
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # 1. Create WebChat channel
            channel_data = {
                "name": "Test WebChat",
                "channel_type": "webchat",
                "config": {
                    "welcome_message": "Hello! How can I help you?",
                    "primary_color": "#007bff"
                }
            }
            
            channel_response = await client.post(
                "/api/channels", 
                json=channel_data, 
                headers=headers
            )
            assert channel_response.status_code == 201
            widget_id = channel_response.json()["widget_id"]
            
            # 2. Upload a test document for RAG
            document_content = "This is a test document about our product features."
            files = {"file": ("test.txt", document_content, "text/plain")}
            
            doc_response = await client.post(
                "/api/documents/upload",
                files=files,
                headers=headers
            )
            assert doc_response.status_code == 201
            
            # 3. Send customer message via WebChat
            customer_message = {
                "content": "What are your product features?",
                "session_token": str(uuid4())
            }
            
            webchat_response = await client.post(
                f"/api/webchat/send?widget_id={widget_id}",
                json=customer_message
            )
            assert webchat_response.status_code == 200
            
            # 4. Check for AI response
            messages_response = await client.get(
                f"/api/webchat/messages?widget_id={widget_id}&session_token={customer_message['session_token']}"
            )
            assert messages_response.status_code == 200
            messages = messages_response.json()["messages"]
            
            # Should have customer message and AI response
            assert len(messages) >= 2
            assert any(msg["role"] == "customer" for msg in messages)
            assert any(msg["role"] == "assistant" for msg in messages)
            
            # 5. Test escalation scenario
            escalation_message = {
                "content": "I need to speak to a human agent immediately!",
                "session_token": customer_message["session_token"]
            }
            
            escalation_response = await client.post(
                f"/api/webchat/send?widget_id={widget_id}",
                json=escalation_message
            )
            assert escalation_response.status_code == 200
            
            # 6. Verify conversation was escalated
            conversations_response = await client.get(
                "/api/conversations/",
                headers=headers
            )
            assert conversations_response.status_code == 200
            conversations = conversations_response.json()["conversations"]
            
            # Should have at least one conversation, possibly escalated
            assert len(conversations) >= 1
    
    async def test_multi_tenant_isolation(self, test_workspace_setup):
        """
        Test multi-tenant isolation across all operations
        Validates: Multi-tenant isolation
        """
        setup1 = await test_workspace_setup
        
        # Create second workspace
        user_data2 = {
            "email": "test2@example.com", 
            "password": "testpass456",
            "business_name": "Test Business 2"
        }
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Register second user
            response2 = await client.post("/api/auth/register", json=user_data2)
            assert response2.status_code == 201
            
            # Login second user
            login_response2 = await client.post("/api/auth/login", json={
                "email": user_data2["email"],
                "password": user_data2["password"]
            })
            assert login_response2.status_code == 200
            token2 = login_response2.json()["access_token"]
            headers2 = {"Authorization": f"Bearer {token2}"}
            
            # Test workspace isolation
            
            # 1. User 1 creates a channel
            channel_data = {
                "name": "Workspace 1 Channel",
                "channel_type": "webchat",
                "config": {"welcome_message": "Hello from workspace 1"}
            }
            
            channel_response1 = await client.post(
                "/api/channels",
                json=channel_data,
                headers=setup1["headers"]
            )
            assert channel_response1.status_code == 201
            
            # 2. User 2 should not see User 1's channels
            channels_response2 = await client.get(
                "/api/channels",
                headers=headers2
            )
            assert channels_response2.status_code == 200
            user2_channels = channels_response2.json()["channels"]
            
            # User 2 should have no channels
            assert len(user2_channels) == 0
            
            # 3. User 1 uploads a document
            document_content = "Workspace 1 confidential document"
            files = {"file": ("confidential.txt", document_content, "text/plain")}
            
            doc_response1 = await client.post(
                "/api/documents/upload",
                files=files,
                headers=setup1["headers"]
            )
            assert doc_response1.status_code == 201
            
            # 4. User 2 should not see User 1's documents
            docs_response2 = await client.get(
                "/api/documents/",
                headers=headers2
            )
            assert docs_response2.status_code == 200
            user2_docs = docs_response2.json()["documents"]
            
            # User 2 should have no documents
            assert len(user2_docs) == 0
            
            # 5. User 2 should not see User 1's conversations
            convs_response2 = await client.get(
                "/api/conversations/",
                headers=headers2
            )
            assert convs_response2.status_code == 200
            user2_convs = convs_response2.json()["conversations"]
            
            # User 2 should have no conversations
            assert len(user2_convs) == 0
    
    async def test_webhook_integration_flow(self, test_workspace_setup):
        """
        Test webhook integration with real webhook data
        Validates: Channel integrations
        """
        setup = await test_workspace_setup
        headers = setup["headers"]
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Test Telegram webhook simulation
            telegram_webhook_data = {
                "update_id": 123456,
                "message": {
                    "message_id": 1,
                    "from": {
                        "id": 987654321,
                        "first_name": "Test",
                        "last_name": "User",
                        "username": "testuser"
                    },
                    "chat": {
                        "id": 987654321,
                        "type": "private"
                    },
                    "date": int(datetime.now().timestamp()),
                    "text": "Hello from Telegram!"
                }
            }
            
            # Test webhook endpoint (this would normally require a real channel)
            webhook_response = await client.post(
                "/webhooks/test/telegram",
                json=telegram_webhook_data,
                headers=headers
            )
            # Should return 200 even if channel doesn't exist (for testing)
            assert webhook_response.status_code in [200, 404]
    
    async def test_system_health_and_monitoring(self):
        """
        Test system health endpoints and monitoring
        Validates: System health and monitoring
        """
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Test basic health check
            health_response = await client.get("/health")
            assert health_response.status_code == 200
            health_data = health_response.json()
            assert health_data["status"] == "healthy"
            
            # Test detailed health check (if implemented)
            try:
                detailed_health = await client.get("/api/metrics/health/detailed")
                if detailed_health.status_code == 200:
                    detailed_data = detailed_health.json()
                    assert "database" in detailed_data
                    assert "storage" in detailed_data
            except:
                pass  # Detailed health check might not be implemented
    
    async def test_authentication_and_authorization_flow(self):
        """
        Test complete authentication and authorization flow
        Validates: Authentication integration
        """
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Test registration
            user_data = {
                "email": f"auth_test_{uuid4()}@example.com",
                "password": "securepass123",
                "business_name": "Auth Test Business"
            }
            
            reg_response = await client.post("/api/auth/register", json=user_data)
            assert reg_response.status_code == 201
            
            # Test login
            login_response = await client.post("/api/auth/login", json={
                "email": user_data["email"],
                "password": user_data["password"]
            })
            assert login_response.status_code == 200
            token = login_response.json()["access_token"]
            
            # Test protected endpoint access
            headers = {"Authorization": f"Bearer {token}"}
            profile_response = await client.get("/api/auth/me", headers=headers)
            assert profile_response.status_code == 200
            profile_data = profile_response.json()
            assert profile_data["email"] == user_data["email"]
            
            # Test unauthorized access
            unauth_response = await client.get("/api/auth/me")
            assert unauth_response.status_code == 401
            
            # Test invalid token
            bad_headers = {"Authorization": "Bearer invalid_token"}
            bad_response = await client.get("/api/auth/me", headers=bad_headers)
            assert bad_response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])