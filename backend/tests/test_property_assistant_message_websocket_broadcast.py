"""
Property-Based Tests for Assistant Message WebSocket Broadcasting
Tests bug condition and preservation properties for the websocket broadcast fix.
"""

import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, call
from sqlalchemy import select

from app.models.workspace import Workspace
from app.models.user import User
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.message_processor import MessageProcessor
from app.services.escalation_router import EscalationRouter
from app.services.websocket_events import notify_new_message


class TestAssistantMessageWebSocketBroadcast:
    """
    Bug Condition Exploration Tests
    These tests verify that assistant messages are NOT broadcast on unfixed code.
    """
    
    @pytest.mark.asyncio
    async def test_bug_condition_escalation_acknowledgment_not_broadcast(self, db_session):
        """
        **Property 1: Bug Condition** - Escalation Acknowledgment Messages Not Broadcast
        
        CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
        
        Test that escalation acknowledgment messages created in escalation_router.py
        are NOT broadcast via websocket on unfixed code.
        
        Validates: Requirements 1.1, 2.1
        """
        # Setup test data - create workspace, user, conversation
        user = User(
            id=uuid4(),
            email="test@example.com",
            hashed_password="test"
        )
        db_session.add(user)
        
        workspace = Workspace(
            id=uuid4(),
            name="Test Workspace",
            owner_id=user.id,
            slug="test-workspace"
        )
        db_session.add(workspace)
        
        channel = Channel(
            id=uuid4(),
            workspace_id=workspace.id,
            type="webchat",
            name="Test Channel",
            is_active=True
        )
        db_session.add(channel)
        
        contact = Contact(
            id=uuid4(),
            workspace_id=workspace.id,
            channel_id=channel.id,
            external_id="test_contact",
            name="Test Contact"
        )
        db_session.add(contact)
        
        conversation = Conversation(
            id=uuid4(),
            workspace_id=workspace.id,
            contact_id=contact.id,
            channel_type="webchat",
            status="active"
        )
        db_session.add(conversation)
        await db_session.commit()
        
        # Track if notify_new_message was called
        notify_called = False
        notify_args = None
        
        async def track_notify(*args, **kwargs):
            nonlocal notify_called, notify_args
            notify_called = True
            notify_args = (args, kwargs)
            return 1  # Return success
        
        # Create escalation router
        router = EscalationRouter(db_session)
        
        # Call send_customer_acknowledgment (this creates the message)
        with patch('app.services.websocket_events.notify_new_message', side_effect=track_notify):
            message = await router.send_customer_acknowledgment(
                conversation_id=str(conversation.id),
                has_agents=True,
                workspace_id=str(workspace.id)
            )
        
        # Verify message was created
        assert message is not None
        assert message.role == "assistant"
        assert message.content is not None
        
        # BUG CONDITION: On unfixed code, notify_new_message should NOT be called
        # This assertion will FAIL on unfixed code (which is expected - proves bug exists)
        # After fix, this will PASS (proves bug is fixed)
        assert notify_called, \
            "EXPECTED BEHAVIOR: notify_new_message should be called after creating escalation acknowledgment message"
        
        # Verify correct parameters were passed
        if notify_called:
            assert notify_args is not None
            kwargs = notify_args[1]
            assert kwargs.get('workspace_id') == str(workspace.id)
            assert kwargs.get('conversation_id') == str(conversation.id)
            assert kwargs.get('message_id') == str(message.id)
    
    @pytest.mark.asyncio
    async def test_bug_condition_blocked_contact_error_not_broadcast(self, db_session):
        """
        **Property 1: Bug Condition** - Blocked Contact Error Messages Not Broadcast
        
        CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
        
        Test that blocked contact error messages created in message_processor.py
        are NOT broadcast via websocket on unfixed code.
        
        Validates: Requirements 1.2, 2.2
        """
        # Setup test data - create workspace, user, channel, blocked contact
        user = User(
            id=uuid4(),
            email="test2@example.com",
            hashed_password="test"
        )
        db_session.add(user)
        
        workspace = Workspace(
            id=uuid4(),
            name="Test Workspace 2",
            owner_id=user.id,
            slug="test-workspace-2"
        )
        db_session.add(workspace)
        
        channel = Channel(
            id=uuid4(),
            workspace_id=workspace.id,
            type="webchat",
            name="Test Channel 2",
            is_active=True
        )
        db_session.add(channel)
        
        # Create blocked contact
        contact = Contact(
            id=uuid4(),
            workspace_id=workspace.id,
            channel_id=channel.id,
            external_id="blocked_contact",
            name="Blocked Contact",
            is_blocked=True  # This contact is blocked
        )
        db_session.add(contact)
        await db_session.commit()
        
        # Track notify_new_message calls
        notify_calls = []
        
        async def track_notify(*args, **kwargs):
            notify_calls.append((args, kwargs))
            return 1
        
        # Create message processor
        processor = MessageProcessor(db_session)
        
        # Try to process message from blocked contact
        with patch('app.services.websocket_events.notify_new_message', side_effect=track_notify):
            try:
                await processor.preprocess_message(
                    workspace_id=str(workspace.id),
                    channel_id=str(channel.id),
                    external_contact_id="blocked_contact",
                    content="Test message from blocked contact",
                    channel_type="webchat"
                )
            except Exception:
                # BlockedContactError is expected
                pass
        
        # BUG CONDITION: On unfixed code, notify_new_message should be called ONCE (for customer message)
        # but NOT for the error message (2 calls expected after fix)
        # This assertion will FAIL on unfixed code (which is expected - proves bug exists)
        # After fix, this will PASS (proves bug is fixed)
        assert len(notify_calls) == 2, \
            f"EXPECTED BEHAVIOR: notify_new_message should be called twice (customer message + error message), got {len(notify_calls)}"
    
    @pytest.mark.asyncio
    async def test_bug_condition_business_hours_auto_reply_not_broadcast(self, db_session):
        """
        **Property 1: Bug Condition** - Business Hours Auto-Reply Messages Not Broadcast
        
        CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
        
        Test that business hours auto-reply messages created in message_processor.py
        are NOT broadcast via websocket on unfixed code.
        
        Validates: Requirements 1.3, 2.3
        """
        # Setup test data
        user = User(
            id=uuid4(),
            email="test3@example.com",
            hashed_password="test"
        )
        db_session.add(user)
        
        workspace = Workspace(
            id=uuid4(),
            name="Test Workspace 3",
            owner_id=user.id,
            slug="test-workspace-3"
        )
        db_session.add(workspace)
        
        channel = Channel(
            id=uuid4(),
            workspace_id=workspace.id,
            type="webchat",
            name="Test Channel 3",
            is_active=True
        )
        db_session.add(channel)
        await db_session.commit()
        
        # Mock business hours service to return outside hours
        async def mock_is_within_business_hours(workspace_id, db):
            return False, "We're currently closed. Our business hours are 9 AM - 5 PM."
        
        async def mock_get_outside_hours_behavior(workspace_id, db):
            return "inform_and_pause"
        
        # Track notify_new_message calls
        notify_calls = []
        
        async def track_notify(*args, **kwargs):
            notify_calls.append((args, kwargs))
            return 1
        
        # Create message processor
        processor = MessageProcessor(db_session)
        
        # Try to process message outside business hours
        with patch('app.services.business_hours_service.is_within_business_hours', side_effect=mock_is_within_business_hours):
            with patch('app.services.business_hours_service.get_outside_hours_behavior', side_effect=mock_get_outside_hours_behavior):
                with patch('app.services.websocket_events.notify_new_message', side_effect=track_notify):
                    try:
                        await processor.preprocess_message(
                            workspace_id=str(workspace.id),
                            channel_id=str(channel.id),
                            external_contact_id="test_contact_3",
                            content="Test message outside business hours",
                            channel_type="webchat"
                        )
                    except Exception:
                        # OutsideBusinessHoursError is expected
                        pass
        
        # BUG CONDITION: On unfixed code, notify_new_message should be called ONCE (for customer message)
        # but NOT for the auto-reply message (2 calls expected after fix)
        # This assertion will FAIL on unfixed code (which is expected - proves bug exists)
        # After fix, this will PASS (proves bug is fixed)
        assert len(notify_calls) == 2, \
            f"EXPECTED BEHAVIOR: notify_new_message should be called twice (customer message + auto-reply), got {len(notify_calls)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
