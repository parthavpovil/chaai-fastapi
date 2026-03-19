"""
Property-Based Test for Message Deduplication
Tests Property 8: Message Deduplication

For any message with the same external_message_id within a conversation,
only the first occurrence should be processed while subsequent duplicates
should be ignored without processing.

Validates: Requirements 3.2
"""

import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite
from uuid import uuid4
from datetime import datetime, timezone
import secrets

from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.message_processor import MessageProcessor, DuplicateMessageError


# Custom strategies for domain objects
@composite
def valid_message_content(draw):
    """Generate valid message content"""
    return draw(st.text(min_size=1, max_size=1000, alphabet=st.characters(
        whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs', 'Po')
    )))


@composite
def external_message_id_strategy(draw):
    """Generate external message IDs (platform-specific format)"""
    # Simulate different platform ID formats
    platform = draw(st.sampled_from(['telegram', 'whatsapp', 'instagram']))
    
    if platform == 'telegram':
        # Telegram uses numeric message IDs
        return f"tg_{draw(st.integers(min_value=1, max_value=999999999))}"
    elif platform == 'whatsapp':
        # WhatsApp uses alphanumeric IDs
        return f"wamid.{secrets.token_hex(16)}"
    else:  # instagram
        # Instagram uses alphanumeric IDs
        return f"ig_{secrets.token_hex(12)}"


class TestMessageDeduplicationProperty:
    """Property tests for message deduplication"""
    
    @given(
        message_content=valid_message_content(),
        external_msg_id=external_message_id_strategy()
    )
    @settings(max_examples=10, deadline=20000)  # Further reduced
    @pytest.mark.asyncio
    async def test_property_8_message_deduplication(
        self, 
        message_content, 
        external_msg_id
    ):
        """
        Property 8: Message Deduplication
        
        For any message with the same external_message_id within a conversation,
        only the first occurrence should be processed while subsequent duplicates
        should be ignored without processing.
        
        Validates: Requirements 3.2
        """
        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Setup: Create test workspace, channel, contact, and conversation
            user = User(
                id=uuid4(),
                email=f"test-{secrets.token_hex(8)}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()
            
            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{secrets.token_hex(8)}",
                tier="free"
            )
            db.add(workspace)
            await db.flush()
            
            # Store IDs before commit
            workspace_id = workspace.id
            
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace_id,
                type="telegram",
                is_active=True,
                config={}
            )
            db.add(channel)
            await db.flush()
            
            contact = Contact(
                id=uuid4(),
                workspace_id=workspace_id,
                channel_id=channel.id,
                external_id=f"contact_{secrets.token_hex(8)}",
                name="Test Contact"
            )
            db.add(contact)
            await db.flush()
            
            conversation = Conversation(
                id=uuid4(),
                workspace_id=workspace_id,
                contact_id=contact.id,
                channel_type="telegram",
                status="ai"
            )
            db.add(conversation)
            await db.flush()
            
            # Store conversation ID
            conversation_id = conversation.id
            
            await db.commit()
            
            # Initialize message processor
            processor = MessageProcessor(db)
            
            # Test 1: First message with external_message_id should NOT be a duplicate
            is_duplicate_first = await processor.check_message_duplicate(
                workspace_id=str(workspace_id),
                external_message_id=external_msg_id,
                conversation_id=str(conversation_id)
            )
            assert is_duplicate_first == False, \
                "First message should not be detected as duplicate"
            
            # Create the first message
            first_message = Message(
                id=uuid4(),
                conversation_id=conversation_id,
                role="customer",
                content=message_content,
                channel_type="telegram",
                external_message_id=external_msg_id
            )
            db.add(first_message)
            await db.commit()
            
            # Test 2: Subsequent messages with same external_message_id should be duplicates
            is_duplicate = await processor.check_message_duplicate(
                workspace_id=str(workspace_id),
                external_message_id=external_msg_id,
                conversation_id=str(conversation_id)
            )
            assert is_duplicate == True, \
                "Duplicate message should be detected as duplicate"
            
            # Test 3: Database constraint should prevent duplicate insertion
            duplicate_message = Message(
                id=uuid4(),
                conversation_id=conversation_id,
                role="customer",
                content=f"Duplicate: {message_content}",
                channel_type="telegram",
                external_message_id=external_msg_id
            )
            db.add(duplicate_message)
            
            from sqlalchemy.exc import IntegrityError
            with pytest.raises(IntegrityError):
                await db.commit()
            
            await db.rollback()
            
            # Test 4: Messages without external_message_id (WebChat) should never be duplicates
            is_duplicate_none = await processor.check_message_duplicate(
                workspace_id=str(workspace_id),
                external_message_id=None,
                conversation_id=str(conversation_id)
            )
            assert is_duplicate_none == False, \
                "Messages without external_message_id should never be duplicates"
            
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        message_content=valid_message_content()
    )
    @settings(max_examples=10, deadline=20000)  # Reduced examples
    @pytest.mark.asyncio
    async def test_property_8_deduplication_with_preprocessing(
        self, 
        message_content
    ):
        """
        Property 8 Extension: Message Deduplication in Preprocessing Pipeline
        
        Tests that the preprocess_message function properly raises DuplicateMessageError
        when duplicate messages are detected, preventing any further processing.
        
        Validates: Requirements 3.2
        """
        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Setup: Create test workspace and channel
            user = User(
                id=uuid4(),
                email=f"test-{secrets.token_hex(8)}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()
            
            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{secrets.token_hex(8)}",
                tier="free"
            )
            db.add(workspace)
            await db.flush()
            
            workspace_id = workspace.id
            
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace_id,
                type="telegram",
                is_active=True,
                config={}
            )
            db.add(channel)
            await db.flush()
            
            channel_id = channel.id
            await db.commit()
            
            # Initialize message processor
            processor = MessageProcessor(db)
            
            # Generate unique external message ID
            external_msg_id = f"tg_{secrets.token_hex(16)}"
            external_contact_id = f"contact_{secrets.token_hex(8)}"
            
            # Test 1: First message should process successfully
            result = await processor.preprocess_message(
                workspace_id=str(workspace_id),
                channel_id=str(channel_id),
                external_contact_id=external_contact_id,
                content=message_content,
                external_message_id=external_msg_id,
                contact_name="Test Contact"
            )
            
            # Verify preprocessing succeeded
            assert result is not None
            assert "message" in result
            assert "conversation" in result
            assert "contact" in result
            assert result["message"].external_message_id == external_msg_id
            
            # Test 2: Subsequent message with same external_message_id should raise DuplicateMessageError
            with pytest.raises(DuplicateMessageError) as exc_info:
                await processor.preprocess_message(
                    workspace_id=str(workspace_id),
                    channel_id=str(channel_id),
                    external_contact_id=external_contact_id,
                    content=f"Duplicate: {message_content}",
                    external_message_id=external_msg_id,  # Same external ID
                    contact_name="Test Contact"
                )
            
            # Verify error message contains the external_message_id
            assert external_msg_id in str(exc_info.value), \
                "Error message should contain the duplicate external_message_id"
            
            # Test 3: Messages without external_message_id should all process successfully
            for i in range(2):
                result = await processor.preprocess_message(
                    workspace_id=str(workspace_id),
                    channel_id=str(channel_id),
                    external_contact_id=external_contact_id,
                    content=f"WebChat {i}: {message_content}",
                    external_message_id=None,  # No external ID
                    contact_name="Test Contact"
                )
                
                # All should succeed
                assert result is not None
                assert result["message"].external_message_id is None
            
        finally:
            # Cleanup
            await db.rollback()
            await db.close()


if __name__ == "__main__":
    # Run property tests with verbose output
    pytest.main([__file__, "-v", "--tb=short"])
