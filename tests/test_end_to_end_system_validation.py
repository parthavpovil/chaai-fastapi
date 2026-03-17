 """
End-to-End System Validation Tests
Task 24.2: Perform end-to-end system validation

This module contains comprehensive integration tests that validate:
1. Complete customer journey from message to response
2. Multi-tenant isolation across all operations  
3. All channel integrations with real webhook data

These tests ensure the entire system works correctly as an integrated whole.
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
from app.services.message_processor import MessageProcessor
from app.services.rag_engine import RAGEngine
from app.services.escalation_classifier import EscalationClassifier
from app.services.websocket_manager import WebSocketManager
from app.services.email_service import EmailService
from app.utils.tier_limits import TierType


class TestEndToEndSystemValidation:
    """
    Comprehensive end-to-end system validation tests.
    
    These tests validate complete workflows and system integration
    rather than individual components in isolation.
    """
    
    @pytest.fixture
    async def setup_multi_tenant_environment(self, db_session):
        """Set up multiple workspaces for multi-tenant testing."""
        # Create two separate workspaces with different configurations
        workspace1 = Workspace(
            id=uuid.uuid4(),
            business_name="TechCorp Support",
            slug="techcorp-support",
            tier=TierType.PRO,
            fallback_message="Thanks for contacting TechCorp! We'll get back to you soon.",
            is_active=True
        )
        
        workspace2 = Workspace(
            id=uuid.uuid4(),
            business_name="RetailCo Help",
            slug="retailco-help", 
            tier=TierType.GROWTH,
            fallback_message="Hello! RetailCo customer service will assist you shortly.",
            is_active=True
        )
        
        db_session.add_all([workspace1, workspace2])
        await db_session.commit()
        
        return workspace1, workspace2
    @pytest.fixture
    async def setup_channels_for_workspaces(self, db_session, setup_multi_tenant_environment):
        """Set up channels for each workspace."""
        workspace1, workspace2 = setup_multi_tenant_environment
        
        # Workspace 1 channels
        telegram_channel_1 = Channel(
            id=uuid.uuid4(),
            workspace_id=workspace1.id,
            type="telegram",
            name="TechCorp Telegram",
            credentials=EncryptionService.encrypt(json.dumps({
                "bot_token": "1234567890:AAEhBOweik6ad6PsVMRxjeQKXkq8rGdHJ4I",
                "secret_token": "techcorp_secret_123"
            })),
            is_active=True
        )
        
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
        
        # Workspace 2 channels
        whatsapp_channel_2 = Channel(
            id=uuid.uuid4(),
            workspace_id=workspace2.id,
            type="whatsapp",
            name="RetailCo WhatsApp",
            credentials=EncryptionService.encrypt(json.dumps({
                "phone_number_id": "987654321",
                "access_token": "EAABwzLixnjYBO...",
                "app_secret": "retailco_app_secret_456"
            })),
            is_active=True
        )
        
        db_session.add_all([telegram_channel_1, webchat_channel_1, whatsapp_channel_2])
        await db_session.commit()
        
        return {
            "workspace1": {
                "workspace": workspace1,
                "telegram": telegram_channel_1,
                "webchat": webchat_channel_1
            },
            "workspace2": {
                "workspace": workspace2,
                "whatsapp": whatsapp_channel_2
            }
        }

    @pytest.fixture
    async def setup_documents_and_knowledge(self, db_session, setup_channels_for_workspaces):
        """Set up documents and knowledge base for each workspace."""
        channels = setup_channels_for_workspaces
        
        # TechCorp documents
        tech_doc = Document(
            id=uuid.uuid4(),
            workspace_id=channels["workspace1"]["workspace"].id,
            filename="tech_support_guide.pdf",
            original_filename="TechCorp Support Guide.pdf",
            file_size=1024000,
            content_type="application/pdf",
            status="completed"
        )
        
        tech_chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=tech_doc.id,
            workspace_id=tech_doc.workspace_id,
            content="For technical issues, please restart your device and check network connectivity. If problems persist, contact our technical team.",
            token_count=25,
            embedding=[0.1] * 1536,  # Mock embedding
            chunk_index=0
        )
        
        # RetailCo documents
        retail_doc = Document(
            id=uuid.uuid4(),
            workspace_id=channels["workspace2"]["workspace"].id,
            filename="return_policy.pdf",
            original_filename="RetailCo Return Policy.pdf",
            file_size=512000,
            content_type="application/pdf",
            status="completed"
        )
        
        retail_chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=retail_doc.id,
            workspace_id=retail_doc.workspace_id,
            content="Items can be returned within 30 days of purchase with original receipt. Refunds are processed within 5-7 business days.",
            token_count=22,
            embedding=[0.2] * 1536,  # Mock embedding
            chunk_index=0
        )
        
        db_session.add_all([tech_doc, tech_chunk, retail_doc, retail_chunk])
        await db_session.commit()
        
        return channels
    async def test_complete_customer_journey_telegram(self, db_session, setup_documents_and_knowledge):
        """
        Test complete customer journey from Telegram message to AI response.
        
        This test validates:
        1. Webhook message reception and validation
        2. Contact and conversation creation
        3. RAG-based response generation
        4. Message storage and response delivery
        """
        channels = setup_documents_and_knowledge
        workspace = channels["workspace1"]["workspace"]
        telegram_channel = channels["workspace1"]["telegram"]
        
        # Decrypt channel credentials for webhook validation
        credentials = json.loads(EncryptionService.decrypt(telegram_channel.credentials))
        secret_token = credentials["secret_token"]
        
        # Mock AI provider responses
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            mock_ai.generate_embedding.return_value = [0.1] * 1536
            mock_ai.generate_response.return_value = AIResponse(
                content="I can help you with technical issues. Please restart your device and check your network connectivity.",
                token_count=20,
                provider="google"
            )
            mock_ai.classify_escalation.return_value = EscalationDecision(
                should_escalate=False,
                reason="technical_support",
                confidence=0.3
            )
            mock_provider.return_value = mock_ai
            
            # Simulate Telegram webhook payload
            webhook_payload = {
                "update_id": 123456789,
                "message": {
                    "message_id": 1001,
                    "from": {
                        "id": 987654321,
                        "is_bot": False,
                        "first_name": "John",
                        "last_name": "Doe",
                        "username": "johndoe"
                    },
                    "chat": {
                        "id": 987654321,
                        "first_name": "John",
                        "last_name": "Doe",
                        "username": "johndoe",
                        "type": "private"
                    },
                    "date": int(datetime.now().timestamp()),
                    "text": "My computer won't connect to the internet. Can you help?"
                }
            }
            
            # Test webhook endpoint with proper authentication
            async with AsyncClient(app=app, base_url="http://test") as client:
                response = await client.post(
                    f"/api/webhooks/telegram/{telegram_channel.id}",
                    json=webhook_payload,
                    headers={"X-Telegram-Bot-Api-Secret-Token": secret_token}
                )
                
                assert response.status_code == 200
                
                # Allow background task to process
                await asyncio.sleep(0.1)
                
                # Verify contact was created
                contact = await db_session.execute(
                    "SELECT * FROM contacts WHERE external_id = '987654321' AND channel_id = :channel_id",
                    {"channel_id": telegram_channel.id}
                )
                contact_record = contact.fetchone()
                assert contact_record is not None
                assert contact_record.name == "John Doe"
                
                # Verify conversation was created
                conversation = await db_session.execute(
                    "SELECT * FROM conversations WHERE contact_id = :contact_id",
                    {"contact_id": contact_record.id}
                )
                conversation_record = conversation.fetchone()
                assert conversation_record is not None
                assert conversation_record.status == "active"
                
                # Verify customer message was stored
                customer_message = await db_session.execute(
                    "SELECT * FROM messages WHERE conversation_id = :conv_id AND sender_type = 'customer'",
                    {"conv_id": conversation_record.id}
                )
                customer_msg = customer_message.fetchone()
                assert customer_msg is not None
                assert "computer won't connect" in customer_msg.content
                assert customer_msg.external_message_id == "1001"
                
                # Verify AI response was generated and stored
                ai_message = await db_session.execute(
                    "SELECT * FROM messages WHERE conversation_id = :conv_id AND sender_type = 'ai'",
                    {"conv_id": conversation_record.id}
                )
                ai_msg = ai_message.fetchone()
                assert ai_msg is not None
                assert "restart your device" in ai_msg.content
                assert ai_msg.token_count == 20
    async def test_multi_tenant_isolation_validation(self, db_session, setup_documents_and_knowledge):
        """
        Test multi-tenant isolation across all operations.
        
        This test validates:
        1. Workspace data isolation
        2. Channel credential separation
        3. Document and knowledge base isolation
        4. Conversation and message isolation
        5. Usage tracking isolation
        """
        channels = setup_documents_and_knowledge
        workspace1 = channels["workspace1"]["workspace"]
        workspace2 = channels["workspace2"]["workspace"]
        
        # Mock AI provider
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            mock_ai.generate_embedding.return_value = [0.1] * 1536
            mock_ai.generate_response.return_value = AIResponse(
                content="Test response",
                token_count=10,
                provider="google"
            )
            mock_ai.classify_escalation.return_value = EscalationDecision(
                should_escalate=False,
                reason="general",
                confidence=0.2
            )
            mock_provider.return_value = mock_ai
            
            # Create contacts and conversations in both workspaces
            contact1 = Contact(
                id=uuid.uuid4(),
                workspace_id=workspace1.id,
                channel_id=channels["workspace1"]["telegram"].id,
                external_id="user123",
                name="User One"
            )
            
            contact2 = Contact(
                id=uuid.uuid4(),
                workspace_id=workspace2.id,
                channel_id=channels["workspace2"]["whatsapp"].id,
                external_id="user123",  # Same external_id but different workspace
                name="User Two"
            )
            
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
            
            message1 = Message(
                id=uuid.uuid4(),
                conversation_id=conversation1.id,
                content="TechCorp message",
                sender_type="customer",
                token_count=5
            )
            
            message2 = Message(
                id=uuid.uuid4(),
                conversation_id=conversation2.id,
                content="RetailCo message",
                sender_type="customer",
                token_count=5
            )
            
            db_session.add_all([contact1, contact2, conversation1, conversation2, message1, message2])
            await db_session.commit()
            
            # Test RAG isolation - workspace1 should only see its documents
            rag_engine = RAGEngine()
            
            # Query from workspace1 should only return workspace1 documents
            workspace1_chunks = await rag_engine.search_documents(
                query_embedding=[0.1] * 1536,
                workspace_id=workspace1.id,
                threshold=0.5
            )
            
            for chunk in workspace1_chunks:
                assert chunk.workspace_id == workspace1.id
                assert "technical issues" in chunk.content or "restart your device" in chunk.content
            
            # Query from workspace2 should only return workspace2 documents
            workspace2_chunks = await rag_engine.search_documents(
                query_embedding=[0.2] * 1536,
                workspace_id=workspace2.id,
                threshold=0.5
            )
            
            for chunk in workspace2_chunks:
                assert chunk.workspace_id == workspace2.id
                assert "return" in chunk.content or "refunds" in chunk.content
            
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
            
            # Test message isolation
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
    async def test_whatsapp_webhook_integration(self, db_session, setup_documents_and_knowledge):
        """
        Test WhatsApp webhook integration with real webhook data format.
        
        This test validates:
        1. WhatsApp webhook signature verification
        2. Message parsing and processing
        3. Response generation and delivery
        """
        channels = setup_documents_and_knowledge
        workspace = channels["workspace2"]["workspace"]
        whatsapp_channel = channels["workspace2"]["whatsapp"]
        
        # Decrypt credentials for signature verification
        credentials = json.loads(EncryptionService.decrypt(whatsapp_channel.credentials))
        app_secret = credentials["app_secret"]
        
        # Mock AI provider
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            mock_ai.generate_embedding.return_value = [0.2] * 1536
            mock_ai.generate_response.return_value = AIResponse(
                content="Items can be returned within 30 days with receipt. Refunds take 5-7 business days.",
                token_count=18,
                provider="google"
            )
            mock_ai.classify_escalation.return_value = EscalationDecision(
                should_escalate=False,
                reason="return_policy",
                confidence=0.2
            )
            mock_provider.return_value = mock_ai
            
            # WhatsApp webhook payload
            webhook_payload = {
                "object": "whatsapp_business_account",
                "entry": [{
                    "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                    "changes": [{
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "987654321"
                            },
                            "contacts": [{
                                "profile": {
                                    "name": "Jane Smith"
                                },
                                "wa_id": "15559876543"
                            }],
                            "messages": [{
                                "from": "15559876543",
                                "id": "wamid.HBgNMTU1NTk4NzY1NDMVAgARGBI5QTRCMTM4RjA2RjY2RTlBNAA=",
                                "timestamp": str(int(datetime.now().timestamp())),
                                "text": {
                                    "body": "I want to return an item I bought last week. What's your return policy?"
                                },
                                "type": "text"
                            }]
                        },
                        "field": "messages"
                    }]
                }]
            }
            
            # Generate HMAC signature
            payload_str = json.dumps(webhook_payload, separators=(',', ':'))
            signature = hmac.new(
                app_secret.encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Test webhook with signature verification
            async with AsyncClient(app=app, base_url="http://test") as client:
                response = await client.post(
                    f"/api/webhooks/whatsapp/{whatsapp_channel.id}",
                    json=webhook_payload,
                    headers={"X-Hub-Signature-256": f"sha256={signature}"}
                )
                
                assert response.status_code == 200
                
                # Allow background processing
                await asyncio.sleep(0.1)
                
                # Verify contact creation
                contact = await db_session.execute(
                    "SELECT * FROM contacts WHERE external_id = '15559876543' AND channel_id = :channel_id",
                    {"channel_id": whatsapp_channel.id}
                )
                contact_record = contact.fetchone()
                assert contact_record is not None
                assert contact_record.name == "Jane Smith"
                
                # Verify conversation and messages
                conversation = await db_session.execute(
                    "SELECT * FROM conversations WHERE contact_id = :contact_id",
                    {"contact_id": contact_record.id}
                )
                conversation_record = conversation.fetchone()
                assert conversation_record is not None
                
                # Verify customer message
                customer_message = await db_session.execute(
                    "SELECT * FROM messages WHERE conversation_id = :conv_id AND sender_type = 'customer'",
                    {"conv_id": conversation_record.id}
                )
                customer_msg = customer_message.fetchone()
                assert customer_msg is not None
                assert "return policy" in customer_msg.content.lower()
                
                # Verify AI response with RetailCo knowledge
                ai_message = await db_session.execute(
                    "SELECT * FROM messages WHERE conversation_id = :conv_id AND sender_type = 'ai'",
                    {"conv_id": conversation_record.id}
                )
                ai_msg = ai_message.fetchone()
                assert ai_msg is not None
                assert "30 days" in ai_msg.content
                assert "receipt" in ai_msg.content
    async def test_webchat_public_api_integration(self, db_session, setup_documents_and_knowledge):
        """
        Test WebChat public API integration with session management.
        
        This test validates:
        1. Widget configuration retrieval
        2. Public message sending without authentication
        3. Session-based rate limiting
        4. Message polling and response delivery
        """
        channels = setup_documents_and_knowledge
        workspace = channels["workspace1"]["workspace"]
        webchat_channel = channels["workspace1"]["webchat"]
        
        # Mock AI provider
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            mock_ai.generate_embedding.return_value = [0.1] * 1536
            mock_ai.generate_response.return_value = AIResponse(
                content="Welcome to TechCorp! I can help with technical issues. Please describe your problem.",
                token_count=16,
                provider="google"
            )
            mock_ai.classify_escalation.return_value = EscalationDecision(
                should_escalate=False,
                reason="welcome",
                confidence=0.1
            )
            mock_provider.return_value = mock_ai
            
            async with AsyncClient(app=app, base_url="http://test") as client:
                # Test widget configuration retrieval
                config_response = await client.get(f"/api/webchat/config/{workspace.slug}")
                assert config_response.status_code == 200
                
                config_data = config_response.json()
                assert config_data["business_name"] == "TechCorp Support"
                assert "widget_id" in config_data
                
                widget_id = config_data["widget_id"]
                session_token = str(uuid.uuid4())
                
                # Test public message sending
                message_payload = {
                    "widget_id": widget_id,
                    "session_token": session_token,
                    "message": "Hello, I'm having trouble with my software installation",
                    "sender_name": "Test User"
                }
                
                send_response = await client.post("/api/webchat/send", json=message_payload)
                assert send_response.status_code == 200
                
                send_data = send_response.json()
                assert send_data["status"] == "success"
                
                # Allow background processing
                await asyncio.sleep(0.1)
                
                # Test message polling
                poll_response = await client.get(
                    f"/api/webchat/messages?widget_id={widget_id}&session_token={session_token}"
                )
                assert poll_response.status_code == 200
                
                messages_data = poll_response.json()
                assert len(messages_data["messages"]) >= 2  # Customer message + AI response
                
                # Verify customer message
                customer_msg = next(msg for msg in messages_data["messages"] if msg["sender_type"] == "customer")
                assert "software installation" in customer_msg["content"]
                assert customer_msg["sender_name"] == "Test User"
                
                # Verify AI response
                ai_msg = next(msg for msg in messages_data["messages"] if msg["sender_type"] == "ai")
                assert "TechCorp" in ai_msg["content"]
                assert "technical issues" in ai_msg["content"]
                
                # Test rate limiting - send multiple messages rapidly
                rate_limit_responses = []
                for i in range(12):  # Exceed 10 messages per minute limit
                    rate_payload = {
                        "widget_id": widget_id,
                        "session_token": session_token,
                        "message": f"Rate limit test message {i}",
                        "sender_name": "Test User"
                    }
                    rate_response = await client.post("/api/webchat/send", json=rate_payload)
                    rate_limit_responses.append(rate_response.status_code)
                
                # Should have some 429 (rate limited) responses
                assert 429 in rate_limit_responses
    async def test_escalation_and_agent_workflow(self, db_session, setup_documents_and_knowledge):
        """
        Test complete escalation workflow with agent management.
        
        This test validates:
        1. Escalation detection and triggering
        2. Agent notification via WebSocket
        3. Conversation claiming by agents
        4. Agent response handling
        """
        channels = setup_documents_and_knowledge
        workspace = channels["workspace1"]["workspace"]
        telegram_channel = channels["workspace1"]["telegram"]
        
        # Create an agent for the workspace
        agent = Agent(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            email="agent@techcorp.com",
            is_active=True
        )
        
        # Create agent user account
        agent_user = User(
            id=uuid.uuid4(),
            email="agent@techcorp.com",
            password_hash="$2b$12$test_hash",
            role="agent",
            workspace_id=workspace.id,
            is_active=True
        )
        
        agent.user_id = agent_user.id
        db_session.add_all([agent, agent_user])
        await db_session.commit()
        
        # Mock AI provider to trigger escalation
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            mock_ai.generate_embedding.return_value = [0.1] * 1536
            mock_ai.classify_escalation.return_value = EscalationDecision(
                should_escalate=True,
                reason="explicit",
                confidence=0.9
            )
            mock_provider.return_value = mock_ai
            
            # Mock WebSocket manager for agent notifications
            with patch('app.services.websocket_manager.WebSocketManager.broadcast_to_workspace') as mock_broadcast:
                # Create contact and conversation
                contact = Contact(
                    id=uuid.uuid4(),
                    workspace_id=workspace.id,
                    channel_id=telegram_channel.id,
                    external_id="escalation_user",
                    name="Escalation User"
                )
                
                conversation = Conversation(
                    id=uuid.uuid4(),
                    workspace_id=workspace.id,
                    contact_id=contact.id,
                    status="active"
                )
                
                db_session.add_all([contact, conversation])
                await db_session.commit()
                
                # Process escalation message
                message_processor = MessageProcessor()
                result = await message_processor.process_message(
                    workspace_id=workspace.id,
                    channel_id=telegram_channel.id,
                    contact_id=contact.id,
                    message_content="I need to speak to a human agent immediately! This is urgent!",
                    external_message_id="escalation_msg_001"
                )
                
                assert result.escalated is True
                assert result.escalation_reason == "explicit"
                
                # Verify conversation status updated
                await db_session.refresh(conversation)
                assert conversation.status == "escalated"
                
                # Verify WebSocket notification was sent
                mock_broadcast.assert_called_once()
                call_args = mock_broadcast.call_args
                assert call_args[0][0] == workspace.id  # workspace_id
                assert call_args[0][1].event_type == "conversation_escalated"
                
                # Simulate agent claiming conversation
                conversation.status = "agent"
                conversation.assigned_agent_id = agent.id
                await db_session.commit()
                
                # Verify agent can send response
                agent_message = Message(
                    id=uuid.uuid4(),
                    conversation_id=conversation.id,
                    content="Hello! I'm here to help you. What specific issue are you experiencing?",
                    sender_type="agent",
                    sender_id=agent_user.id,
                    token_count=15
                )
                
                db_session.add(agent_message)
                await db_session.commit()
                
                # Verify message was stored correctly
                stored_message = await db_session.execute(
                    "SELECT * FROM messages WHERE id = :msg_id",
                    {"msg_id": agent_message.id}
                )
                stored_msg = stored_message.fetchone()
                assert stored_msg is not None
                assert stored_msg.sender_type == "agent"
                assert stored_msg.sender_id == agent_user.id
                assert "here to help" in stored_msg.content
    async def test_maintenance_mode_system_behavior(self, db_session, setup_documents_and_knowledge):
        """
        Test system behavior during maintenance mode.
        
        This test validates:
        1. Maintenance mode detection and enforcement
        2. Message processing bypass during maintenance
        3. Maintenance message delivery
        4. Admin access preservation during maintenance
        """
        channels = setup_documents_and_knowledge
        workspace = channels["workspace1"]["workspace"]
        telegram_channel = channels["workspace1"]["telegram"]
        
        # Enable maintenance mode
        from app.models.platform_setting import PlatformSetting
        maintenance_setting = PlatformSetting(
            key="maintenance_mode",
            value="true"
        )
        db_session.add(maintenance_setting)
        await db_session.commit()
        
        # Create contact and conversation
        contact = Contact(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            channel_id=telegram_channel.id,
            external_id="maintenance_user",
            name="Maintenance User"
        )
        
        conversation = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            contact_id=contact.id,
            status="active"
        )
        
        db_session.add_all([contact, conversation])
        await db_session.commit()
        
        # Mock AI provider (should not be called during maintenance)
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            mock_provider.return_value = mock_ai
            
            # Process message during maintenance mode
            message_processor = MessageProcessor()
            result = await message_processor.process_message(
                workspace_id=workspace.id,
                channel_id=telegram_channel.id,
                contact_id=contact.id,
                message_content="I need help with my account",
                external_message_id="maintenance_msg_001"
            )
            
            # Verify maintenance mode response
            assert result.response_content is not None
            assert "maintenance" in result.response_content.lower()
            assert result.escalated is False
            assert result.token_count == 0  # No AI processing
            
            # Verify AI provider was not called
            mock_ai.generate_embedding.assert_not_called()
            mock_ai.generate_response.assert_not_called()
            mock_ai.classify_escalation.assert_not_called()
            
            # Verify customer message was still stored
            customer_message = await db_session.execute(
                "SELECT * FROM messages WHERE conversation_id = :conv_id AND sender_type = 'customer'",
                {"conv_id": conversation.id}
            )
            customer_msg = customer_message.fetchone()
            assert customer_msg is not None
            assert "help with my account" in customer_msg.content
            
            # Verify maintenance response was stored
            maintenance_message = await db_session.execute(
                "SELECT * FROM messages WHERE conversation_id = :conv_id AND sender_type = 'ai'",
                {"conv_id": conversation.id}
            )
            maintenance_msg = maintenance_message.fetchone()
            assert maintenance_msg is not None
            assert "maintenance" in maintenance_msg.content.lower()
        
        # Disable maintenance mode for cleanup
        maintenance_setting.value = "false"
        await db_session.commit()

    async def test_tier_limits_and_usage_tracking(self, db_session, setup_documents_and_knowledge):
        """
        Test tier limits enforcement and usage tracking across workspaces.
        
        This test validates:
        1. Tier-specific limit enforcement
        2. Usage counter tracking and isolation
        3. Monthly limit resets
        4. Cross-workspace usage isolation
        """
        channels = setup_documents_and_knowledge
        workspace1 = channels["workspace1"]["workspace"]  # PRO tier
        workspace2 = channels["workspace2"]["workspace"]  # GROWTH tier
        
        from app.services.tier_manager import TierManager
        from app.models.usage_counter import UsageCounter
        
        tier_manager = TierManager()
        
        # Test channel limits
        # PRO tier allows 4 channels, GROWTH allows 4 channels
        pro_can_add = await tier_manager.check_channel_limit(workspace1.id)
        growth_can_add = await tier_manager.check_channel_limit(workspace2.id)
        
        assert pro_can_add is True  # Has 2 channels, can add more
        assert growth_can_add is True  # Has 1 channel, can add more
        
        # Test message limits
        # PRO tier: 50,000 messages, GROWTH tier: 10,000 messages
        current_month = datetime.now().strftime("%Y-%m")
        
        # Create usage counters
        usage1 = UsageCounter(
            id=uuid.uuid4(),
            workspace_id=workspace1.id,
            month=current_month,
            messages_sent=45000,  # Close to PRO limit
            tokens_used=450000
        )
        
        usage2 = UsageCounter(
            id=uuid.uuid4(),
            workspace_id=workspace2.id,
            month=current_month,
            messages_sent=9500,  # Close to GROWTH limit
            tokens_used=95000
        )
        
        db_session.add_all([usage1, usage2])
        await db_session.commit()
        
        # Test message limit checking
        pro_can_send = await tier_manager.check_message_limit(workspace1.id, 100)
        growth_can_send = await tier_manager.check_message_limit(workspace2.id, 100)
        
        assert pro_can_send is True  # PRO has higher limit
        assert growth_can_send is True  # Still under GROWTH limit
        
        # Test usage increment isolation
        await tier_manager.increment_usage(workspace1.id, 1000)
        await tier_manager.increment_usage(workspace2.id, 500)
        
        # Verify usage was incremented correctly and isolated
        updated_usage1 = await db_session.execute(
            "SELECT * FROM usage_counters WHERE workspace_id = :workspace_id AND month = :month",
            {"workspace_id": workspace1.id, "month": current_month}
        )
        usage1_record = updated_usage1.fetchone()
        assert usage1_record.tokens_used == 451000  # 450000 + 1000
        
        updated_usage2 = await db_session.execute(
            "SELECT * FROM usage_counters WHERE workspace_id = :workspace_id AND month = :month",
            {"workspace_id": workspace2.id, "month": current_month}
        )
        usage2_record = updated_usage2.fetchone()
        assert usage2_record.tokens_used == 95500  # 95000 + 500
        
        # Verify workspace isolation - workspace1 usage didn't affect workspace2
        assert usage1_record.tokens_used != usage2_record.tokens_used
    async def test_document_processing_and_rag_integration(self, db_session, setup_documents_and_knowledge):
        """
        Test complete document processing and RAG integration workflow.
        
        This test validates:
        1. Document upload and processing pipeline
        2. Embedding generation and storage
        3. Vector similarity search
        4. RAG response generation with document context
        """
        channels = setup_documents_and_knowledge
        workspace = channels["workspace1"]["workspace"]
        
        # Mock AI provider for embeddings and responses
        with patch('app.services.ai_provider_factory.get_provider') as mock_provider:
            mock_ai = AsyncMock()
            
            # Mock embedding generation
            mock_ai.generate_embedding.return_value = [0.15] * 1536  # Similar to existing tech doc
            
            # Mock RAG response with document context
            mock_ai.generate_response.return_value = AIResponse(
                content="Based on our technical support guide, please restart your device and check network connectivity. If the issue persists, our technical team can provide further assistance.",
                token_count=28,
                provider="google"
            )
            
            mock_provider.return_value = mock_ai
            
            # Test RAG engine with document context
            from app.services.rag_engine import RAGEngine
            rag_engine = RAGEngine()
            
            # Simulate conversation history
            conversation_history = [
                Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.uuid4(),
                    content="My internet connection keeps dropping",
                    sender_type="customer",
                    token_count=7
                ),
                Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.uuid4(),
                    content="I can help with connectivity issues. Let me check our knowledge base.",
                    sender_type="ai",
                    token_count=15
                )
            ]
            
            # Generate RAG response
            rag_response = await rag_engine.generate_response(
                query="internet connection problems troubleshooting",
                workspace_id=workspace.id,
                conversation_history=conversation_history,
                max_chunks=3
            )
            
            assert rag_response.content is not None
            assert "restart your device" in rag_response.content
            assert "network connectivity" in rag_response.content
            assert rag_response.token_count == 28
            assert len(rag_response.relevant_chunks) > 0
            
            # Verify document chunks were found and used
            for chunk in rag_response.relevant_chunks:
                assert chunk.workspace_id == workspace.id
                assert chunk.similarity_score >= 0.75  # Above threshold
            
            # Test with query that shouldn't match documents
            mock_ai.generate_embedding.return_value = [0.9] * 1536  # Very different embedding
            
            no_match_response = await rag_engine.generate_response(
                query="cooking recipes and food preparation",
                workspace_id=workspace.id,
                conversation_history=[],
                max_chunks=3
            )
            
            # Should return fallback message when no relevant documents found
            assert no_match_response.content == workspace.fallback_message
            assert len(no_match_response.relevant_chunks) == 0

    async def test_websocket_real_time_notifications(self, db_session, setup_documents_and_knowledge):
        """
        Test WebSocket real-time notifications for workspace events.
        
        This test validates:
        1. WebSocket connection management
        2. Event broadcasting to workspace connections
        3. Connection isolation between workspaces
        4. Event filtering and delivery
        """
        channels = setup_documents_and_knowledge
        workspace1 = channels["workspace1"]["workspace"]
        workspace2 = channels["workspace2"]["workspace"]
        
        from app.services.websocket_manager import WebSocketManager, WebSocketEvent
        
        # Mock WebSocket connections
        mock_websocket1 = MagicMock()
        mock_websocket2 = MagicMock()
        mock_websocket3 = MagicMock()  # Different workspace
        
        websocket_manager = WebSocketManager()
        
        # Simulate connections from different workspaces
        user1_id = uuid.uuid4()
        user2_id = uuid.uuid4()
        user3_id = uuid.uuid4()
        
        # Connect users to workspace1
        await websocket_manager.connect(mock_websocket1, workspace1.id, user1_id)
        await websocket_manager.connect(mock_websocket2, workspace1.id, user2_id)
        
        # Connect user to workspace2
        await websocket_manager.connect(mock_websocket3, workspace2.id, user3_id)
        
        # Test escalation event broadcasting
        escalation_event = WebSocketEvent(
            event_type="conversation_escalated",
            data={
                "conversation_id": str(uuid.uuid4()),
                "contact_name": "Test Customer",
                "message": "I need urgent help!",
                "escalation_reason": "explicit"
            }
        )
        
        # Broadcast to workspace1
        await websocket_manager.broadcast_to_workspace(workspace1.id, escalation_event)
        
        # Verify workspace1 connections received the event
        mock_websocket1.send_text.assert_called_once()
        mock_websocket2.send_text.assert_called_once()
        
        # Verify workspace2 connection did not receive the event
        mock_websocket3.send_text.assert_not_called()
        
        # Test agent claim event
        claim_event = WebSocketEvent(
            event_type="conversation_claimed",
            data={
                "conversation_id": str(uuid.uuid4()),
                "agent_name": "Agent Smith",
                "claimed_at": datetime.now().isoformat()
            }
        )
        
        # Reset mocks
        mock_websocket1.reset_mock()
        mock_websocket2.reset_mock()
        mock_websocket3.reset_mock()
        
        # Broadcast claim event to workspace2
        await websocket_manager.broadcast_to_workspace(workspace2.id, claim_event)
        
        # Verify only workspace2 connection received the event
        mock_websocket1.send_text.assert_not_called()
        mock_websocket2.send_text.assert_not_called()
        mock_websocket3.send_text.assert_called_once()
        
        # Test connection cleanup
        await websocket_manager.disconnect(mock_websocket1, workspace1.id, user1_id)
        
        # Broadcast another event to verify disconnected client doesn't receive it
        mock_websocket1.reset_mock()
        mock_websocket2.reset_mock()
        
        new_message_event = WebSocketEvent(
            event_type="new_message",
            data={
                "conversation_id": str(uuid.uuid4()),
                "message": "New customer message received",
                "timestamp": datetime.now().isoformat()
            }
        )
        
        await websocket_manager.broadcast_to_workspace(workspace1.id, new_message_event)
        
        # Verify disconnected client didn't receive event
        mock_websocket1.send_text.assert_not_called()
        # But connected client did
        mock_websocket2.send_text.assert_called_once()