"""
Simple Integration Tests for Message Processing Pipeline
Tests the integration points between components without complex database setup
"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.routers.webhooks import process_webhook_background
from app.services.message_processor import MessageProcessingError


class TestPipelineIntegrationSimple:
    """Test pipeline integration with simplified mocking"""
    
    @pytest.mark.asyncio
    async def test_webhook_to_message_processor_integration(self):
        """Test webhook handler correctly calls message processor"""
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 123,
                "text": "Hello, I need help",
                "from": {"id": 456789, "first_name": "John"},
                "chat": {"id": 456789, "type": "private"},
                "date": 1640995200
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock channel
        mock_channel = MagicMock()
        mock_channel.id = "test-channel-id"
        mock_channel.workspace_id = "test-workspace-id"
        
        # Mock conversation and message
        mock_conversation = MagicMock()
        mock_conversation.id = "test-conversation-id"
        mock_message = MagicMock()
        mock_message.id = "test-message-id"
        
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.message_processor.process_incoming_message') as mock_process_message, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.rag_engine.generate_rag_response') as mock_rag, \
             patch('app.services.websocket_events.notify_new_message') as mock_websocket, \
             patch('app.services.usage_tracker.track_message_usage') as mock_usage, \
             patch('app.routers.webhooks.send_platform_response') as mock_platform_response:
            
            # Configure mocks
            mock_get_channel.return_value = mock_channel
            mock_process_message.return_value = {
                "conversation": mock_conversation,
                "message": mock_message,
                "workspace_id": "test-workspace-id",
                "channel_id": "test-channel-id"
            }
            mock_escalation.return_value = None  # No escalation
            mock_rag.return_value = {
                "response": "I can help you with that.",
                "input_tokens": 10,
                "output_tokens": 15,
                "total_tokens": 25
            }
            mock_websocket.return_value = 1
            mock_usage.return_value = {"message_count": 1}
            mock_platform_response.return_value = True
            
            # Process webhook
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=mock_db
            )
            
            # Verify message processor was called with correct parameters
            mock_process_message.assert_called_once()
            call_args = mock_process_message.call_args[1]
            assert call_args["workspace_id"] == "test-workspace-id"
            assert call_args["channel_id"] == "test-channel-id"
            assert call_args["content"] == "Hello, I need help"
            assert call_args["external_contact_id"] == "456789"
            assert call_args["external_message_id"] == "123"
    
    @pytest.mark.asyncio
    async def test_escalation_integration_with_websocket(self):
        """Test escalation service integration with WebSocket notifications"""
        
        # Mock webhook payload with escalation trigger
        telegram_payload = {
            "message": {
                "message_id": 124,
                "text": "I want to speak to a human agent!",
                "from": {"id": 456790, "first_name": "Jane"},
                "chat": {"id": 456790, "type": "private"},
                "date": 1640995300
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock channel
        mock_channel = MagicMock()
        mock_channel.id = "test-channel-id"
        mock_channel.workspace_id = "test-workspace-id"
        
        # Mock conversation and message
        mock_conversation = MagicMock()
        mock_conversation.id = "test-conversation-id"
        mock_message = MagicMock()
        mock_message.id = "test-message-id"
        
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.message_processor.process_incoming_message') as mock_process_message, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation:
            
            # Configure mocks
            mock_get_channel.return_value = mock_channel
            mock_process_message.return_value = {
                "conversation": mock_conversation,
                "message": mock_message,
                "workspace_id": "test-workspace-id",
                "channel_id": "test-channel-id"
            }
            
            # Mock escalation result
            mock_escalation.return_value = {
                "success": True,
                "escalation_reason": "explicit",
                "priority": "high",
                "has_agents": True,
                "notifications_sent": True
            }
            
            # Process webhook
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=mock_db
            )
            
            # Verify escalation was called
            mock_escalation.assert_called_once()
            escalation_args = mock_escalation.call_args[1]
            assert escalation_args["conversation_id"] == "test-conversation-id"
            assert escalation_args["workspace_id"] == "test-workspace-id"
            assert escalation_args["message_content"] == "I want to speak to a human agent!"
    
    @pytest.mark.asyncio
    async def test_rag_integration_with_response_creation(self):
        """Test RAG engine integration with response message creation"""
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 125,
                "text": "What are your business hours?",
                "from": {"id": 456791, "first_name": "Bob"},
                "chat": {"id": 456791, "type": "private"},
                "date": 1640995400
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock channel
        mock_channel = MagicMock()
        mock_channel.id = "test-channel-id"
        mock_channel.workspace_id = "test-workspace-id"
        
        # Mock conversation and message
        mock_conversation = MagicMock()
        mock_conversation.id = "test-conversation-id"
        mock_message = MagicMock()
        mock_message.id = "test-message-id"
        
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.message_processor.process_incoming_message') as mock_process_message, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.rag_engine.generate_rag_response') as mock_rag, \
             patch('app.services.message_processor.MessageProcessor.create_message') as mock_create_message, \
             patch('app.services.websocket_events.notify_new_message') as mock_websocket, \
             patch('app.services.usage_tracker.track_message_usage') as mock_usage, \
             patch('app.routers.webhooks.send_platform_response') as mock_platform_response:
            
            # Configure mocks
            mock_get_channel.return_value = mock_channel
            mock_process_message.return_value = {
                "conversation": mock_conversation,
                "message": mock_message,
                "workspace_id": "test-workspace-id",
                "channel_id": "test-channel-id"
            }
            mock_escalation.return_value = None  # No escalation
            
            # Mock RAG response
            mock_rag.return_value = {
                "response": "Our business hours are Monday to Friday, 9 AM to 5 PM.",
                "input_tokens": 12,
                "output_tokens": 18,
                "total_tokens": 30,
                "relevant_chunks_count": 1,
                "chunks_used": [{"chunk_id": "chunk-1", "similarity": 0.85}],
                "has_conversation_context": False,
                "used_fallback": False
            }
            
            # Mock response message creation
            mock_response_message = MagicMock()
            mock_response_message.id = "response-message-id"
            mock_create_message.return_value = mock_response_message
            
            mock_websocket.return_value = 2
            mock_usage.return_value = {"message_count": 1, "total_tokens": 30}
            mock_platform_response.return_value = True
            
            # Process webhook
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=mock_db
            )
            
            # Verify RAG was called with correct parameters
            mock_rag.assert_called_once()
            rag_args = mock_rag.call_args[1]
            assert rag_args["workspace_id"] == "test-workspace-id"
            assert rag_args["query"] == "What are your business hours?"
            assert rag_args["conversation_id"] == "test-conversation-id"
            assert rag_args["max_tokens"] == 300
            
            # Verify response message was created
            mock_create_message.assert_called_once()
            create_args = mock_create_message.call_args[1]
            assert create_args["conversation_id"] == "test-conversation-id"
            assert create_args["content"] == "Our business hours are Monday to Friday, 9 AM to 5 PM."
            assert create_args["role"] == "assistant"
            assert create_args["channel_type"] == "telegram"
            assert create_args["metadata"]["rag_used"] is True
            assert create_args["metadata"]["input_tokens"] == 12
            assert create_args["metadata"]["output_tokens"] == 18
    
    @pytest.mark.asyncio
    async def test_error_handling_maintains_pipeline_flow(self):
        """Test that errors in one component don't break the entire pipeline"""
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 126,
                "text": "Test error handling",
                "from": {"id": 456792, "first_name": "Error"},
                "chat": {"id": 456792, "type": "private"},
                "date": 1640995500
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock channel
        mock_channel = MagicMock()
        mock_channel.id = "test-channel-id"
        mock_channel.workspace_id = "test-workspace-id"
        
        # Mock conversation and message
        mock_conversation = MagicMock()
        mock_conversation.id = "test-conversation-id"
        mock_message = MagicMock()
        mock_message.id = "test-message-id"
        
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.message_processor.process_incoming_message') as mock_process_message, \
             patch('app.services.escalation_router.check_and_escalate_message') as mock_escalation, \
             patch('app.services.rag_engine.generate_rag_response') as mock_rag, \
             patch('app.services.message_processor.MessageProcessor.create_message') as mock_create_message, \
             patch('app.services.websocket_events.notify_new_message') as mock_websocket, \
             patch('app.services.usage_tracker.track_message_usage') as mock_usage, \
             patch('app.routers.webhooks.send_platform_response') as mock_platform_response:
            
            # Configure mocks - RAG fails but pipeline continues
            mock_get_channel.return_value = mock_channel
            mock_process_message.return_value = {
                "conversation": mock_conversation,
                "message": mock_message,
                "workspace_id": "test-workspace-id",
                "channel_id": "test-channel-id"
            }
            mock_escalation.return_value = None  # No escalation
            
            # Mock RAG failure
            mock_rag.side_effect = Exception("RAG service temporarily unavailable")
            
            # Mock fallback response message creation
            mock_response_message = MagicMock()
            mock_response_message.id = "fallback-message-id"
            mock_create_message.return_value = mock_response_message
            
            mock_websocket.return_value = 1
            mock_usage.return_value = {"message_count": 1, "total_tokens": 0}
            mock_platform_response.return_value = True
            
            # Process webhook - should handle RAG failure gracefully
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=mock_db
            )
            
            # Verify RAG was attempted
            mock_rag.assert_called_once()
            
            # Verify fallback response was created
            mock_create_message.assert_called_once()
            create_args = mock_create_message.call_args[1]
            assert "trouble processing" in create_args["content"].lower()
            assert create_args["role"] == "assistant"
            
            # Verify other services were still called
            mock_websocket.assert_called_once()
            mock_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_maintenance_mode_handling(self):
        """Test maintenance mode handling in the pipeline"""
        
        # Mock webhook payload
        telegram_payload = {
            "message": {
                "message_id": 127,
                "text": "Hello during maintenance",
                "from": {"id": 456793, "first_name": "Maintenance"},
                "chat": {"id": 456793, "type": "private"},
                "date": 1640995600
            }
        }
        
        payload_bytes = json.dumps(telegram_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock channel
        mock_channel = MagicMock()
        mock_channel.id = "test-channel-id"
        mock_channel.workspace_id = "test-workspace-id"
        
        with patch('app.services.webhook_handlers.WebhookHandlers.get_channel_by_webhook_path') as mock_get_channel, \
             patch('app.services.message_processor.process_incoming_message') as mock_process_message:
            
            # Configure mocks
            mock_get_channel.return_value = mock_channel
            
            # Mock maintenance mode error
            mock_process_message.side_effect = MessageProcessingError("System is under maintenance. Please try again later.")
            
            # Process webhook - should handle maintenance mode gracefully
            await process_webhook_background(
                channel_type="telegram",
                payload=payload_bytes,
                headers=headers,
                identifier="test_token",
                db=mock_db
            )
            
            # Verify message processing was attempted
            mock_process_message.assert_called_once()
            
            # Verify the error was handled gracefully (no exception raised)
            # The function should complete without raising an exception
    
    @pytest.mark.asyncio
    async def test_webhook_verification_bypass(self):
        """Test that webhook verification challenges are handled correctly"""
        
        # Mock Meta verification challenge payload
        verification_payload = {
            "hub.challenge": "test_challenge_123",
            "hub.verify_token": "test_verify_token"
        }
        
        payload_bytes = json.dumps(verification_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        
        # Mock database session
        mock_db = AsyncMock()
        
        with patch('app.services.webhook_handlers.WebhookHandlers.handle_whatsapp_webhook') as mock_handler:
            
            # Configure mock to return verification response
            mock_handler.return_value = {
                "status": "verification",
                "challenge": "test_challenge_123",
                "verify_token": "test_verify_token"
            }
            
            # Process webhook
            await process_webhook_background(
                channel_type="whatsapp",
                payload=payload_bytes,
                headers=headers,
                identifier="test_phone_id",
                db=mock_db
            )
            
            # Verify webhook handler was called
            mock_handler.assert_called_once()
            call_args = mock_handler.call_args
            assert call_args[0][0] == payload_bytes  # payload
            assert call_args[0][1] == headers  # headers
            assert call_args[0][2] == "test_phone_id"  # identifier
            
            # Verification should complete without further processing
            # (no message processing, RAG, etc. should be called)