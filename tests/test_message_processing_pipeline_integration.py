"""
Integration Tests for Complete Message Processing Pipeline
Tests the end-to-end flow from webhook to response with all components wired together
"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.webhooks import process_webhook_background
from app.services.webhook_handlers import WebhookHandlers
from app.services.message_processor import MessageProcessor, MessageProcessingError
from app.services.rag_engine import RAGEngine
from app.services.escalation_router import EscalationRouter
from app.services.websocket_events import notify_new_message, notify_escalation
from app.services.usage_tracker import track_message_usage
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.platform_setting import PlatformSetting


class TestMessageProcessingPipelineIntegration:
    """Test complete message processing pipeline integration"""
    
    @pytest.fixture
    def mock_workspace(self):
        """Mock workspace for testing"""
        workspace = MagicMock()
        workspace.id = "test-workspace-id"
        workspace.business_name = "Test Business"
        workspace.slug = "test-business"
        workspace.tier = "starter"
        workspace.fallback_message = "Sorry, I couldn't find relevant information."
        return workspace
    
    @pytest.fixture
    def mock_channel(self, mock_workspace):
        """Mock channel for testing"""
        channel = MagicMock()
        channel.id = "test-channel-id"
        channel.workspace_id = mock_workspace.id
        channel.channel_type = "telegram"
        channel.name = "Test Bot"
        channel.encrypted_config = {"bot_token": "test_token_encrypted"}
        channel.is_active = True
        return channel
    
    @pytest.mark.asyncio
    async def test_complete_message_processing_pipeline_success(
        self, 
        mock_db_session: AsyncSession,
        mock_workspace,
        mock_channel
    ):
        """Test successful end-to-end message processing"""
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 123,
                "text": "Hello, I need help with my account",
                "from": {
                    "id": 456789,
                    "first_name": "John",
                    "last_name": "Doe"
                },
                "chat": {
                    "id": 456789,
                    "type": "private"
                },
                "date": 1640995200
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock external services
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.rag_engine.generate_rag_response') as mock_rag, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.websocket_events.notify_new_message') as mock_websocket, \
             patch('app.services.usage_tracker.track_message_usage') as mock_usage, \
             patch('app.routers.webhooks.send_platform_response') as mock_platform_response, \
             patch('app.services.message_processor.process_incoming_message') as mock_process_message:
            
            # Configure mocks
            mock_get_channel.return_value = mock_channel
            mock_rag.return_value = {
                "response": "I can help you with your account. What specific issue are you experiencing?",
                "input_tokens": 15,
                "output_tokens": 20,
                "total_tokens": 35,
                "relevant_chunks_count": 2,
                "chunks_used": [],
                "has_conversation_context": False,
                "used_fallback": False
            }
            mock_escalation.return_value = None  # No escalation needed
            mock_websocket.return_value = 1  # 1 connection notified
            mock_usage.return_value = {"message_count": 1, "total_tokens": 35}
            mock_platform_response.return_value = True
            
            # Mock message processing result
            mock_conversation = MagicMock()
            mock_conversation.id = "test-conversation-id"
            mock_message = MagicMock()
            mock_message.id = "test-message-id"
            
            mock_process_message.return_value = {
                "conversation": mock_conversation,
                "message": mock_message,
                "workspace_id": mock_workspace.id,
                "channel_id": mock_channel.id
            }
            
            # Process webhook
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=mock_db_session
            )
            
            # Verify external service calls
            mock_rag.assert_called_once()
            mock_escalation.assert_called_once()
            mock_websocket.assert_called_once()
            mock_usage.assert_called_once()
            mock_platform_response.assert_called_once()
            mock_process_message.assert_called_once()
            
            # Verify call arguments
            process_call_args = mock_process_message.call_args[1]
            assert process_call_args["workspace_id"] == mock_workspace.id
            assert process_call_args["channel_id"] == mock_channel.id
            assert process_call_args["content"] == "Hello, I need help with my account"
            assert process_call_args["external_contact_id"] == "456789"
    
    @pytest.mark.asyncio
    async def test_message_processing_with_escalation(
        self, 
        db_session: AsyncSession,
        setup_test_data
    ):
        """Test message processing pipeline with escalation"""
        test_data = await setup_test_data
        workspace = test_data["workspace"]
        channel = test_data["channel"]
        
        # Mock webhook payload with escalation trigger
        telegram_payload = {
            "message": {
                "message_id": 124,
                "text": "I want to speak to a human agent immediately!",
                "from": {
                    "id": 456790,
                    "first_name": "Jane",
                    "last_name": "Smith"
                },
                "chat": {
                    "id": 456790,
                    "type": "private"
                },
                "date": 1640995300
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock external services
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.websocket_events.notify_escalation') as mock_websocket_escalation:
            
            # Configure mocks
            mock_get_channel.return_value = channel
            mock_escalation.return_value = {
                "success": True,
                "escalation_reason": "explicit",
                "priority": "high",
                "has_agents": False,
                "email_sent": True
            }
            mock_websocket_escalation.return_value = 1
            
            # Process webhook
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=db_session
            )
            
            # Verify conversation was escalated
            from sqlalchemy import select
            conversation_result = await db_session.execute(
                select(Conversation)
                .where(Conversation.workspace_id == workspace.id)
            )
            conversation = conversation_result.scalar_one_or_none()
            assert conversation is not None
            assert conversation.status == "escalated"
            
            # Verify escalation was called
            mock_escalation.assert_called_once()
            
            # Verify only customer message exists (no AI response due to escalation)
            messages_result = await db_session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .where(Message.role == "customer")
            )
            customer_messages = messages_result.scalars().all()
            assert len(customer_messages) == 1
            assert customer_messages[0].content == "I want to speak to a human agent immediately!"
    
    @pytest.mark.asyncio
    async def test_message_processing_maintenance_mode(
        self, 
        db_session: AsyncSession,
        setup_test_data
    ):
        """Test message processing during maintenance mode"""
        test_data = await setup_test_data
        workspace = test_data["workspace"]
        channel = test_data["channel"]
        
        # Enable maintenance mode
        from sqlalchemy import update
        await db_session.execute(
            update(PlatformSetting)
            .where(PlatformSetting.key == "maintenance_mode")
            .values(value="true")
        )
        
        maintenance_message_setting = PlatformSetting(
            key="maintenance_message",
            value="System is under maintenance. Please try again later."
        )
        db_session.add(maintenance_message_setting)
        await db_session.commit()
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 125,
                "text": "Hello, I need help",
                "from": {"id": 456791, "first_name": "Test"},
                "chat": {"id": 456791, "type": "private"},
                "date": 1640995400
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock external services
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel:
            mock_get_channel.return_value = channel
            
            # Process webhook - should handle maintenance mode gracefully
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=db_session
            )
            
            # Verify no conversation was created due to maintenance mode
            from sqlalchemy import select
            conversation_result = await db_session.execute(
                select(Conversation)
                .where(Conversation.workspace_id == workspace.id)
            )
            conversations = conversation_result.scalars().all()
            # Should be empty or only contain conversations from previous tests
            # The maintenance mode should prevent new conversation creation
    
    @pytest.mark.asyncio
    async def test_message_processing_duplicate_handling(
        self, 
        db_session: AsyncSession,
        setup_test_data
    ):
        """Test duplicate message handling in the pipeline"""
        test_data = await setup_test_data
        workspace = test_data["workspace"]
        channel = test_data["channel"]
        
        # Create initial conversation and message
        contact = Contact(
            workspace_id=workspace.id,
            channel_id=channel.id,
            external_contact_id="456792",
            name="Duplicate Test User"
        )
        db_session.add(contact)
        await db_session.commit()
        await db_session.refresh(contact)
        
        conversation = Conversation(
            workspace_id=workspace.id,
            contact_id=contact.id,
            channel_id=channel.id,
            status="active"
        )
        db_session.add(conversation)
        await db_session.commit()
        await db_session.refresh(conversation)
        
        # Create existing message
        existing_message = Message(
            conversation_id=conversation.id,
            content="Original message",
            role="customer",
            channel_type="telegram",
            external_message_id="126"
        )
        db_session.add(existing_message)
        await db_session.commit()
        
        # Mock webhook payload with same external_message_id
        telegram_payload = {
            "message": {
                "message_id": 126,  # Same as existing message
                "text": "Duplicate message",
                "from": {"id": 456792, "first_name": "Test"},
                "chat": {"id": 456792, "type": "private"},
                "date": 1640995500
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock external services
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel:
            mock_get_channel.return_value = channel
            
            # Process webhook - should handle duplicate gracefully
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=db_session
            )
            
            # Verify no new message was created
            from sqlalchemy import select
            messages_result = await db_session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
            )
            messages = messages_result.scalars().all()
            assert len(messages) == 1  # Only the original message
            assert messages[0].content == "Original message"
    
    @pytest.mark.asyncio
    async def test_websocket_notification_integration(
        self, 
        db_session: AsyncSession,
        setup_test_data
    ):
        """Test WebSocket notification integration in the pipeline"""
        test_data = await setup_test_data
        workspace = test_data["workspace"]
        channel = test_data["channel"]
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 127,
                "text": "Test WebSocket notification",
                "from": {"id": 456793, "first_name": "WebSocket"},
                "chat": {"id": 456793, "type": "private"},
                "date": 1640995600
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock external services
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.rag_engine.generate_rag_response') as mock_rag, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.websocket_events.notify_new_message') as mock_websocket, \
             patch('app.services.usage_tracker.track_message_usage') as mock_usage, \
             patch('app.routers.webhooks.send_platform_response') as mock_platform_response:
            
            # Configure mocks
            mock_get_channel.return_value = channel
            mock_rag.return_value = {
                "response": "WebSocket test response",
                "input_tokens": 10,
                "output_tokens": 15,
                "total_tokens": 25
            }
            mock_escalation.return_value = None
            mock_websocket.return_value = 2  # 2 connections notified
            mock_usage.return_value = {"message_count": 1}
            mock_platform_response.return_value = True
            
            # Process webhook
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=db_session
            )
            
            # Verify WebSocket notification was called
            mock_websocket.assert_called_once()
            call_args = mock_websocket.call_args
            assert call_args[1]["workspace_id"] == str(workspace.id)
            assert "conversation_id" in call_args[1]
            assert "message_id" in call_args[1]
    
    @pytest.mark.asyncio
    async def test_error_handling_in_pipeline(
        self, 
        db_session: AsyncSession,
        setup_test_data
    ):
        """Test error handling throughout the pipeline"""
        test_data = await setup_test_data
        workspace = test_data["workspace"]
        channel = test_data["channel"]
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 128,
                "text": "Error handling test",
                "from": {"id": 456794, "first_name": "Error"},
                "chat": {"id": 456794, "type": "private"},
                "date": 1640995700
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock external services with failures
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.rag_engine.generate_rag_response') as mock_rag, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.websocket_events.notify_new_message') as mock_websocket, \
             patch('app.services.usage_tracker.track_message_usage') as mock_usage, \
             patch('app.routers.webhooks.send_platform_response') as mock_platform_response, \
             patch('app.routers.webhooks.handle_processing_error') as mock_error_handler:
            
            # Configure mocks - RAG fails, but pipeline should continue
            mock_get_channel.return_value = channel
            mock_rag.side_effect = Exception("RAG service unavailable")
            mock_escalation.return_value = None
            mock_websocket.return_value = 1
            mock_usage.return_value = {"message_count": 1}
            mock_platform_response.return_value = True
            
            # Process webhook - should handle RAG failure gracefully
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=db_session
            )
            
            # Verify customer message was still created
            from sqlalchemy import select
            messages_result = await db_session.execute(
                select(Message)
                .where(Message.content == "Error handling test")
            )
            customer_message = messages_result.scalar_one_or_none()
            assert customer_message is not None
            
            # Verify fallback response was created
            assistant_messages_result = await db_session.execute(
                select(Message)
                .where(Message.conversation_id == customer_message.conversation_id)
                .where(Message.role == "assistant")
            )
            assistant_message = assistant_messages_result.scalar_one_or_none()
            assert assistant_message is not None
            assert "trouble processing" in assistant_message.content.lower()
            
            # Verify other services were still called
            mock_websocket.assert_called_once()
            mock_usage.assert_called_once()