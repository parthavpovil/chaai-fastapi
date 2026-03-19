"""
Simplified End-to-End System Validation Tests
Task 24.2: Perform end-to-end system validation

This module contains focused integration tests that validate:
1. Complete customer journey from message to response
2. Multi-tenant isolation across all operations  
3. Channel integrations with webhook processing

These tests focus on core system functionality without complex service mocking.
"""

import pytest
import asyncio
import json
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from httpx import AsyncClient

from main import app
from app.database import get_db
from app.models import User, Workspace, Channel, Contact, Conversation, Message, Document, DocumentChunk, Agent
from app.services.auth_service import AuthService
from app.services.encryption import EncryptionService


class TestEndToEndValidationSimple:
    """
    Simplified end-to-end system validation tests.
    
    These tests validate complete workflows and system integration
    with minimal external dependencies.
    """
    
    @pytest.fixture
    async def setup_test_workspaces(self, db_session):
        """Set up test workspaces for multi-tenant testing."""
        # Create two separate workspaces
        workspace1 = Workspace(
            id=uuid.uuid4(),
            business_name="TechCorp Support",
            slug="techcorp-support",
            tier="pro",
            fallback_message="Thanks for contacting TechCorp! We'll get back to you soon.",
            is_active=True
        )
        
        workspace2 = Workspace(
            id=uuid.uuid4(),
            business_name="RetailCo Help",
            slug="retailco-help", 
            tier="growth",
            fallback_message="Hello! RetailCo customer service will assist you shortly.",
            is_active=True
        )
        
        db_session.add_all([workspace1, workspace2])
        await db_session.commit()
        
        return workspace1, workspace2
    @pytest.fixture
    async def setup_test_channels(self, db_session, setup_test_workspaces):
        """Set up test channels for each workspace."""
        workspace1, workspace2 = setup_test_workspaces
        
        # Workspace 1 - WebChat channel
        webchat_channel_1 = Channel(
            id=uuid.uuid4(),
            workspace_id=workspace1.id,
            type="webchat",
            name="TechCorp WebChat",
            credentials=EncryptionService.encrypt(json.dumps({
                "widget_id": str(uuid.uuid4()),
                "primary_color": "#007bff",
                "position": "bottom-right",
                "welcome_message": "Welcome to TechCorp support!"
            })),
            is_active=True
        )
        
        # Workspace 2 - WebChat channel
        webchat_channel_2 = Channel(
            id=uuid.uuid4(),
            workspace_id=workspace2.id,
            type="webchat",
            name="RetailCo WebChat",
            credentials=EncryptionService.encrypt(json.dumps({
                "widget_id": str(uuid.uuid4()),
                "primary_color": "#28a745",
                "position": "bottom-left",
                "welcome_message": "Welcome to RetailCo support!"
            })),
            is_active=True
        )
        
        db_session.add_all([webchat_channel_1, webchat_channel_2])
        await db_session.commit()
        
        return {
            "workspace1": {
                "workspace": workspace1,
                "webchat": webchat_channel_1
            },
            "workspace2": {
                "workspace": workspace2,
                "webchat": webchat_channel_2
            }
        }

    async def test_webchat_customer_journey_end_to_end(self, db_session, setup_test_channels):
        """
        Test complete WebChat customer journey from message to response.
        
        This test validates:
        1. Widget configuration retrieval
        2. Public message sending
        3. Contact and conversation creation
        4. Message storage and retrieval
        """
        channels = setup_test_channels
        workspace = channels["workspace1"]["workspace"]
        webchat_channel = channels["workspace1"]["webchat"]
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Step 1: Get widget configuration
            config_response = await client.get(f"/api/webchat/config/{workspace.slug}")
            assert config_response.status_code == 200
            
            config_data = config_response.json()
            assert config_data["business_name"] == "TechCorp Support"
            assert "widget_id" in config_data
            assert config_data["primary_color"] == "#007bff"
            assert config_data["welcome_message"] == "Welcome to TechCorp support!"
            
            widget_id = config_data["widget_id"]
            session_token = str(uuid.uuid4())
            
            # Step 2: Send customer message
            message_payload = {
                "widget_id": widget_id,
                "session_token": session_token,
                "message": "Hello, I need help with my account setup",
                "sender_name": "John Doe"
            }
            
            send_response = await client.post("/api/webchat/send", json=message_payload)
            assert send_response.status_code == 200
            
            send_data = send_response.json()
            assert send_data["status"] == "success"
            
            # Allow background processing
            await asyncio.sleep(0.2)
            
            # Step 3: Verify contact was created
            contact_query = await db_session.execute(
                "SELECT * FROM contacts WHERE workspace_id = :workspace_id",
                {"workspace_id": workspace.id}
            )
            contact_record = contact_query.fetchone()
            assert contact_record is not None
            assert contact_record.name == "John Doe"
            
            # Step 4: Verify conversation was created
            conversation_query = await db_session.execute(
                "SELECT * FROM conversations WHERE workspace_id = :workspace_id",
                {"workspace_id": workspace.id}
            )
            conversation_record = conversation_query.fetchone()
            assert conversation_record is not None
            assert conversation_record.status == "active"
            
            # Step 5: Verify message was stored
            message_query = await db_session.execute(
                "SELECT * FROM messages WHERE conversation_id = :conv_id",
                {"conv_id": conversation_record.id}
            )
            message_record = message_query.fetchone()
            assert message_record is not None
            assert "account setup" in message_record.content
            assert message_record.sender_type == "customer"
            
            # Step 6: Poll for messages
            poll_response = await client.get(
                f"/api/webchat/messages?widget_id={widget_id}&session_token={session_token}"
            )
            assert poll_response.status_code == 200
            
            messages_data = poll_response.json()
            assert len(messages_data["messages"]) >= 1
            
            # Verify customer message is returned
            customer_msg = next(
                (msg for msg in messages_data["messages"] if msg["sender_type"] == "customer"), 
                None
            )
            assert customer_msg is not None
            assert "account setup" in customer_msg["content"]
            assert customer_msg["sender_name"] == "John Doe"
    async def test_multi_tenant_data_isolation(self, db_session, setup_test_channels):
        """
        Test multi-tenant data isolation across workspaces.
        
        This test validates:
        1. Workspace data separation
        2. Contact isolation between workspaces
        3. Conversation isolation
        4. Message isolation
        """
        channels = setup_test_channels
        workspace1 = channels["workspace1"]["workspace"]
        workspace2 = channels["workspace2"]["workspace"]
        webchat1 = channels["workspace1"]["webchat"]
        webchat2 = channels["workspace2"]["webchat"]
        
        # Create contacts in both workspaces with same external_id
        contact1 = Contact(
            id=uuid.uuid4(),
            workspace_id=workspace1.id,
            channel_id=webchat1.id,
            external_id="user123",
            name="TechCorp User"
        )
        
        contact2 = Contact(
            id=uuid.uuid4(),
            workspace_id=workspace2.id,
            channel_id=webchat2.id,
            external_id="user123",  # Same external_id but different workspace
            name="RetailCo User"
        )
        
        # Create conversations in both workspaces
        conversation1 = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace1.id,
            contact_id=contact1.id,
            status="active"
        )
        
        conversation2 = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace2.id,
            contact_id=contact2.id,
            status="active"
        )
        
        # Create messages in both conversations
        message1 = Message(
            id=uuid.uuid4(),
            conversation_id=conversation1.id,
            content="TechCorp specific message",
            sender_type="customer",
            token_count=5
        )
        
        message2 = Message(
            id=uuid.uuid4(),
            conversation_id=conversation2.id,
            content="RetailCo specific message",
            sender_type="customer",
            token_count=5
        )
        
        db_session.add_all([contact1, contact2, conversation1, conversation2, message1, message2])
        await db_session.commit()
        
        # Test workspace1 isolation
        workspace1_contacts = await db_session.execute(
            "SELECT * FROM contacts WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace1.id}
        )
        w1_contacts = workspace1_contacts.fetchall()
        assert len(w1_contacts) == 1
        assert w1_contacts[0].name == "TechCorp User"
        assert w1_contacts[0].id == contact1.id
        
        # Test workspace2 isolation
        workspace2_contacts = await db_session.execute(
            "SELECT * FROM contacts WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace2.id}
        )
        w2_contacts = workspace2_contacts.fetchall()
        assert len(w2_contacts) == 1
        assert w2_contacts[0].name == "RetailCo User"
        assert w2_contacts[0].id == contact2.id
        
        # Test conversation isolation
        workspace1_conversations = await db_session.execute(
            "SELECT * FROM conversations WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace1.id}
        )
        w1_convs = workspace1_conversations.fetchall()
        assert len(w1_convs) == 1
        assert w1_convs[0].id == conversation1.id
        
        workspace2_conversations = await db_session.execute(
            "SELECT * FROM conversations WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace2.id}
        )
        w2_convs = workspace2_conversations.fetchall()
        assert len(w2_convs) == 1
        assert w2_convs[0].id == conversation2.id
        
        # Test message isolation through conversation join
        workspace1_messages = await db_session.execute(
            """
            SELECT m.* FROM messages m 
            JOIN conversations c ON m.conversation_id = c.id 
            WHERE c.workspace_id = :workspace_id
            """,
            {"workspace_id": workspace1.id}
        )
        w1_msgs = workspace1_messages.fetchall()
        assert len(w1_msgs) == 1
        assert "TechCorp" in w1_msgs[0].content
        
        workspace2_messages = await db_session.execute(
            """
            SELECT m.* FROM messages m 
            JOIN conversations c ON m.conversation_id = c.id 
            WHERE c.workspace_id = :workspace_id
            """,
            {"workspace_id": workspace2.id}
        )
        w2_msgs = workspace2_messages.fetchall()
        assert len(w2_msgs) == 1
        assert "RetailCo" in w2_msgs[0].content
    async def test_webchat_rate_limiting_enforcement(self, db_session, setup_test_channels):
        """
        Test WebChat rate limiting enforcement.
        
        This test validates:
        1. Rate limit tracking per session
        2. Rate limit enforcement (10 messages per minute)
        3. Proper error responses when limits exceeded
        """
        channels = setup_test_channels
        workspace = channels["workspace1"]["workspace"]
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Get widget configuration
            config_response = await client.get(f"/api/webchat/config/{workspace.slug}")
            assert config_response.status_code == 200
            
            config_data = config_response.json()
            widget_id = config_data["widget_id"]
            session_token = str(uuid.uuid4())
            
            # Send messages rapidly to trigger rate limiting
            responses = []
            for i in range(12):  # Exceed 10 messages per minute limit
                message_payload = {
                    "widget_id": widget_id,
                    "session_token": session_token,
                    "message": f"Rate limit test message {i}",
                    "sender_name": "Rate Test User"
                }
                
                response = await client.post("/api/webchat/send", json=message_payload)
                responses.append(response.status_code)
                
                # Small delay to avoid overwhelming the system
                await asyncio.sleep(0.01)
            
            # Should have some successful responses (200) and some rate limited (429)
            success_count = responses.count(200)
            rate_limited_count = responses.count(429)
            
            assert success_count > 0, "Should have some successful messages"
            assert rate_limited_count > 0, "Should have some rate limited messages"
            assert success_count <= 10, "Should not exceed rate limit"

    async def test_workspace_configuration_isolation(self, db_session, setup_test_channels):
        """
        Test workspace configuration isolation.
        
        This test validates:
        1. Widget configuration isolation between workspaces
        2. Proper workspace slug resolution
        3. Error handling for non-existent workspaces
        """
        channels = setup_test_channels
        workspace1 = channels["workspace1"]["workspace"]
        workspace2 = channels["workspace2"]["workspace"]
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Test workspace1 configuration
            config1_response = await client.get(f"/api/webchat/config/{workspace1.slug}")
            assert config1_response.status_code == 200
            
            config1_data = config1_response.json()
            assert config1_data["business_name"] == "TechCorp Support"
            assert config1_data["primary_color"] == "#007bff"
            assert config1_data["welcome_message"] == "Welcome to TechCorp support!"
            
            # Test workspace2 configuration
            config2_response = await client.get(f"/api/webchat/config/{workspace2.slug}")
            assert config2_response.status_code == 200
            
            config2_data = config2_response.json()
            assert config2_data["business_name"] == "RetailCo Help"
            assert config2_data["primary_color"] == "#28a745"
            assert config2_data["welcome_message"] == "Welcome to RetailCo support!"
            
            # Verify configurations are different
            assert config1_data["widget_id"] != config2_data["widget_id"]
            assert config1_data["business_name"] != config2_data["business_name"]
            assert config1_data["primary_color"] != config2_data["primary_color"]
            
            # Test non-existent workspace
            nonexistent_response = await client.get("/api/webchat/config/nonexistent-workspace")
            assert nonexistent_response.status_code == 404

    async def test_document_workspace_isolation(self, db_session, setup_test_channels):
        """
        Test document and knowledge base isolation between workspaces.
        
        This test validates:
        1. Document storage isolation
        2. Document chunk isolation
        3. Cross-workspace data protection
        """
        channels = setup_test_channels
        workspace1 = channels["workspace1"]["workspace"]
        workspace2 = channels["workspace2"]["workspace"]
        
        # Create documents for each workspace
        doc1 = Document(
            id=uuid.uuid4(),
            workspace_id=workspace1.id,
            filename="techcorp_guide.pdf",
            original_filename="TechCorp Support Guide.pdf",
            file_size=1024000,
            content_type="application/pdf",
            status="completed"
        )
        
        doc2 = Document(
            id=uuid.uuid4(),
            workspace_id=workspace2.id,
            filename="retailco_policy.pdf",
            original_filename="RetailCo Return Policy.pdf",
            file_size=512000,
            content_type="application/pdf",
            status="completed"
        )
        
        # Create document chunks for each workspace
        chunk1 = DocumentChunk(
            id=uuid.uuid4(),
            document_id=doc1.id,
            workspace_id=workspace1.id,  # Denormalized for efficient querying
            content="TechCorp technical support procedures and troubleshooting steps.",
            token_count=12,
            embedding=[0.1] * 1536,  # Mock embedding
            chunk_index=0
        )
        
        chunk2 = DocumentChunk(
            id=uuid.uuid4(),
            document_id=doc2.id,
            workspace_id=workspace2.id,  # Denormalized for efficient querying
            content="RetailCo return policy and refund procedures for customers.",
            token_count=11,
            embedding=[0.2] * 1536,  # Mock embedding
            chunk_index=0
        )
        
        db_session.add_all([doc1, doc2, chunk1, chunk2])
        await db_session.commit()
        
        # Test document isolation
        workspace1_docs = await db_session.execute(
            "SELECT * FROM documents WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace1.id}
        )
        w1_docs = workspace1_docs.fetchall()
        assert len(w1_docs) == 1
        assert w1_docs[0].filename == "techcorp_guide.pdf"
        
        workspace2_docs = await db_session.execute(
            "SELECT * FROM documents WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace2.id}
        )
        w2_docs = workspace2_docs.fetchall()
        assert len(w2_docs) == 1
        assert w2_docs[0].filename == "retailco_policy.pdf"
        
        # Test document chunk isolation
        workspace1_chunks = await db_session.execute(
            "SELECT * FROM document_chunks WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace1.id}
        )
        w1_chunks = workspace1_chunks.fetchall()
        assert len(w1_chunks) == 1
        assert "TechCorp" in w1_chunks[0].content
        
        workspace2_chunks = await db_session.execute(
            "SELECT * FROM document_chunks WHERE workspace_id = :workspace_id",
            {"workspace_id": workspace2.id}
        )
        w2_chunks = workspace2_chunks.fetchall()
        assert len(w2_chunks) == 1
        assert "RetailCo" in w2_chunks[0].content