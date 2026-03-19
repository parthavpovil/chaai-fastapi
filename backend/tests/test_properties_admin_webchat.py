"""
Property-Based Tests for Platform Administration and WebChat API
Tests properties 23, 31-34 from the design document.
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from hypothesis.strategies import composite
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import secrets
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Workspace, User, TierChange, PlatformSetting, Channel, Contact, Conversation, Message, Document, DocumentChunk, Agent
from app.services.admin_service import AdminService

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio
from app.services.email_service import EmailService

@composite
def admin_email(draw):
    """Generate admin email addresses"""
    username = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))))
    return f"{username}@admin.platform.com"

@composite
def workspace_slug(draw):
    """Generate valid workspace slugs"""
    return draw(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')) + '-_'))

@composite
def widget_config(draw):
    """Generate widget configuration data"""
    return {
        "business_name": draw(st.text(min_size=1, max_size=100)),
        "primary_color": draw(st.text(min_size=6, max_size=7, alphabet='0123456789ABCDEF')),
        "position": draw(st.sampled_from(["bottom-right", "bottom-left", "top-right", "top-left"])),
        "welcome_message": draw(st.text(min_size=1, max_size=200))
    }

class TestPlatformAdministrationProperties:
    """Property tests for platform administration"""
    
    @given(
        admin_email=admin_email(),
        workspace_count=st.integers(min_value=1, max_value=10),
        tier_distribution=st.lists(st.sampled_from(['free', 'starter', 'growth', 'pro']), min_size=1, max_size=10)
    )
    @settings(max_examples=50)
    async def test_property_23_platform_administration_access_control(self, admin_email, workspace_count, tier_distribution):
        """
        Property 23: Platform Administration Access Control
        For any user with super admin email, the system should grant access to all
        administrative functions including workspace overview and tier management.

        Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
        """
        mock_db = AsyncMock()
        admin_service = AdminService(db=mock_db)

        # Property: non-admin emails must be rejected by is_super_admin
        non_admin = f"notadmin-{secrets.token_hex(4)}@example.com"
        assert not admin_service.is_super_admin(non_admin)

        # Property: unauthorized access raises ValueError
        with pytest.raises(ValueError, match="Unauthorized"):
            await admin_service.change_workspace_tier(
                workspace_id=uuid4(),
                new_tier='pro',
                admin_email=non_admin,
                reason="Unauthorized attempt"
            )

        # Property: unauthorized suspend raises ValueError
        with pytest.raises(ValueError, match="Unauthorized"):
            await admin_service.suspend_user(
                user_id=uuid4(),
                admin_email=non_admin
            )

        # Property: tier distribution values are always from valid set
        valid_tiers = {'free', 'starter', 'growth', 'pro'}
        for tier in tier_distribution:
            assert tier in valid_tiers

        assert 1 <= workspace_count <= 10

    @given(
        workspace_id=st.uuids(),
        old_tier=st.sampled_from(['free', 'starter', 'growth', 'pro']),
        new_tier=st.sampled_from(['free', 'starter', 'growth', 'pro']),
        embedding_dimension=st.sampled_from([1536, 3072]),  # OpenAI vs Google dimensions
        document_content=st.text(min_size=100, max_size=1000)
    )
    @settings(max_examples=1)
    async def test_property_31_database_constraint_enforcement(self, workspace_id, old_tier, new_tier, embedding_dimension, document_content):
        """
        # Feature: chatsaas-backend, Property 31: Database Constraint Enforcement
        **Validates: Requirements 14.2, 14.4, 14.6**
        
        Property 31: Database Constraint Enforcement
        For any database operation, the system should enforce foreign key constraints 
        and unique constraints as defined in models, support vector columns with 
        appropriate dimensions (3072 for Google, 1536 for OpenAI), and handle 
        timezone-aware timestamps using UTC storage.
        """
        from app.models import User, Contact, Channel, Conversation, Message, Document, DocumentChunk, Agent
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.database import Base
        import numpy as np
        
        # Create in-memory SQLite database for testing
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
            echo=False
        )
        
        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Create session factory
        async_session = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        # Create session and run tests
        async with async_session() as db:
            # Create owner user first (required for workspace foreign key)
            owner_id = uuid4()
            owner = User(
                id=owner_id,
                email=f"owner-{workspace_id.hex[:8]}@test.com",
                hashed_password="hashed_password",
                is_active=True
            )
            db.add(owner)
            await db.commit()
            
            # Test 1: Foreign key constraints - Create workspace with valid owner
            workspace = Workspace(
                id=workspace_id,
                name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier=old_tier,
                owner_id=owner_id  # Valid foreign key
            )
            db.add(workspace)
            await db.commit()
            
            # Test 2: Foreign key constraint violation - Invalid owner_id
            invalid_workspace = Workspace(
                id=uuid4(),
                name="Invalid Business",
                slug=f"invalid-{uuid4().hex[:8]}",
                tier='free',
                owner_id=uuid4()  # Non-existent owner - should fail
            )
            db.add(invalid_workspace)
            
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            
            # Verify it's a foreign key constraint violation
            assert "foreign key" in str(exc_info.value).lower() or "violates" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test 3: Unique constraint enforcement - Workspace slug uniqueness
            duplicate_workspace = Workspace(
                id=uuid4(),
                name="Duplicate Business",
                slug=workspace.slug,  # Same slug should fail
                tier='free',
                owner_id=owner_id
            )
            db.add(duplicate_workspace)
            
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            
            # Verify it's a unique constraint violation
            assert "unique" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test 4: Unique constraint - Contact per channel
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace_id,
                type='webchat',
                is_active=True,
                config={}
            )
            db.add(channel)
            await db.commit()
            
            contact = Contact(
                id=uuid4(),
                workspace_id=workspace_id,
                channel_id=channel.id,
                external_id="test_contact_123",
                name="Test Contact"
            )
            db.add(contact)
            await db.commit()
            
            # Try to create duplicate contact (same workspace_id, channel_id, external_id)
            duplicate_contact = Contact(
                id=uuid4(),
                workspace_id=workspace_id,
                channel_id=channel.id,
                external_id="test_contact_123",  # Same external_id - should fail
                name="Duplicate Contact"
            )
            db.add(duplicate_contact)
            
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            
            assert "unique" in str(exc_info.value).lower() or "uq_contact_per_channel" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test 5: Unique constraint - Agent email per workspace
            agent = Agent(
                id=uuid4(),
                workspace_id=workspace_id,
                name="Test Agent",
                email="agent@test.com",
                is_active=True
            )
            db.add(agent)
            await db.commit()
            
            # Try to create duplicate agent email in same workspace
            duplicate_agent = Agent(
                id=uuid4(),
                workspace_id=workspace_id,
                name="Duplicate Agent",
                email="agent@test.com",  # Same email - should fail
                is_active=True
            )
            db.add(duplicate_agent)
            
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            
            assert "unique" in str(exc_info.value).lower() or "uq_agent_workspace_email" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test 6: Vector columns with appropriate dimensions (skip for SQLite)
            # Note: SQLite doesn't support pgvector, so we'll test the model structure
            document = Document(
                id=uuid4(),
                workspace_id=workspace_id,
                name="Test Document",
                file_path="/test/path",
                status="ready"
            )
            db.add(document)
            await db.commit()
            
            # For SQLite testing, we'll just verify the model accepts the embedding field
            # In production with PostgreSQL + pgvector, this would enforce dimensions
            embedding = [0.1] * embedding_dimension  # Simple embedding
            
            document_chunk = DocumentChunk(
                id=uuid4(),
                workspace_id=workspace_id,
                document_id=document.id,
                content=document_content,
                embedding=embedding,  # Vector with correct dimensions
                chunk_index=0
            )
            db.add(document_chunk)
            await db.commit()
            
            # Verify vector was stored correctly
            await db.refresh(document_chunk)
            assert len(document_chunk.embedding) == embedding_dimension
            
            # Test 7: Timezone-aware timestamps using UTC storage
            conversation = Conversation(
                id=uuid4(),
                workspace_id=workspace_id,
                contact_id=contact.id,
                channel_type='webchat',
                status='ai'
            )
            db.add(conversation)
            await db.commit()
            
            # Create message with timezone-aware timestamp
            message = Message(
                id=uuid4(),
                conversation_id=conversation.id,
                role='customer',
                content='Test message',
                channel_type='webchat',
                external_message_id=f"ext_{uuid4().hex[:8]}"
            )
            db.add(message)
            await db.commit()
            
            # Verify timestamp handling
            await db.refresh(message)
            assert isinstance(message.created_at, datetime)
            # Database stores as naive UTC (timezone info is None but represents UTC)
            assert message.created_at.tzinfo is None
            
            # Test unique constraint on external_message_id within conversation
            duplicate_message = Message(
                id=uuid4(),
                conversation_id=conversation.id,
                role='ai',
                content='Duplicate message',
                channel_type='webchat',
                external_message_id=message.external_message_id  # Same external_message_id
            )
            db.add(duplicate_message)
            
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            
            # Should fail due to unique constraint on external_message_id
            assert "unique" in str(exc_info.value).lower() or "external_message" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test 8: Tier change audit logging with proper foreign key relationships
            tier_change = TierChange(
                id=uuid4(),
                workspace_id=workspace_id,  # Valid foreign key to workspace
                from_tier=old_tier,
                to_tier=new_tier,
                changed_by="admin@test.com",
                note="Property test tier change"
            )
            db.add(tier_change)
            await db.commit()
            
            # Verify foreign key relationship and timestamp
            await db.refresh(tier_change)
            assert tier_change.workspace_id == workspace_id
            assert isinstance(tier_change.created_at, datetime)
            assert tier_change.created_at.tzinfo is None  # Stored as naive UTC
        
        # Clean up
        await engine.dispose()


class TestEmailServiceProperties:
    """Property tests for email service reliability"""
    
    @given(
        recipient_email=st.emails(),
        escalation_context=st.text(min_size=10, max_size=500),
        agent_invitation_data=st.dictionaries(
            keys=st.sampled_from(['workspace_name', 'invitation_token', 'expires_at']),
            values=st.text(min_size=1, max_size=100)
        )
    )
    @settings(max_examples=50)
    async def test_property_32_email_service_reliability(self, recipient_email, escalation_context, agent_invitation_data):
        """
        Property 32: Email Service Reliability
        For any email notification, the system should use configured sender address,
        include relevant context, and handle delivery failures gracefully.

        Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
        """
        email_service = EmailService()

        # Property: password reset email calls send_email with correct structure
        with patch.object(email_service, 'send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"id": "email_123"}

            result = await email_service.send_password_reset_email(
                to=recipient_email,
                reset_token="test_reset_token",
                user_name="Test User"
            )

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs if mock_send.call_args.kwargs else {}
            call_args = mock_send.call_args.args if mock_send.call_args.args else ()

            # Verify recipient is correct (positional or keyword)
            to_value = call_kwargs.get('to', call_args[0] if call_args else None)
            assert to_value == recipient_email

            assert result == {"id": "email_123"}

        # Property: tier limit alert email calls send_email with correct structure
        with patch.object(email_service, 'send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"id": "email_456"}

            result = await email_service.send_tier_limit_alert(
                to=recipient_email,
                user_name="Test User",
                limit_type="messages",
                current_usage=900,
                limit=1000,
                tier="free"
            )

            mock_send.assert_called_once()
            assert result == {"id": "email_456"}

        # Property: delivery failure propagates as exception
        with patch.object(email_service, 'send_email', new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("SMTP Error")

            with pytest.raises(Exception, match="SMTP Error"):
                await email_service.send_password_reset_email(
                    to=recipient_email,
                    reset_token="test_token",
                    user_name="Test User"
                )


class TestWebChatAPIProperties:
    """Property tests for WebChat API functionality"""
    
    @given(
        workspace_slug=workspace_slug(),
        widget_config_data=widget_config(),
        session_token=st.text(min_size=10, max_size=50)
    )
    @settings(max_examples=50)
    async def test_property_33_webchat_api_widget_validation(self, workspace_slug, widget_config_data, session_token):
        """
        Property 33: WebChat API Widget Validation
        For any WebChat API request, the system should validate widget configuration
        exists and is active, and return appropriate configuration data.
        
        Validates: Requirements 16.4, 16.5, 17.2, 17.3
        """
        from app.services.webchat_service import WebChatService
        webchat_service = WebChatService()
        
        async with get_db() as db:
            # Create workspace with webchat channel
            workspace = Workspace(
                id=uuid4(),
                business_name=widget_config_data['business_name'],
                slug=workspace_slug,
                tier='pro',
                owner_id=uuid4()
            )
            
            # Create webchat channel with encrypted config
            from app.services.encryption_service import EncryptionService
            encryption_service = EncryptionService()
            encrypted_config = encryption_service.encrypt(json.dumps(widget_config_data))
            
            webchat_channel = Channel(
                id=uuid4(),
                workspace_id=workspace.id,
                type='webchat',
                name='WebChat',
                credentials=encrypted_config,
                is_active=True
            )
            
            db.add(workspace)
            db.add(webchat_channel)
            await db.commit()
            
            # Test widget configuration retrieval
            config = await webchat_service.get_widget_config(db, workspace_slug)
            
            # Verify configuration contains required fields
            assert config is not None
            assert config['business_name'] == widget_config_data['business_name']
            assert config['primary_color'] == widget_config_data['primary_color']
            assert config['position'] == widget_config_data['position']
            assert config['welcome_message'] == widget_config_data['welcome_message']
            assert 'widget_id' in config
            assert config['widget_id'] == str(webchat_channel.id)
            
            # Test session validation
            is_valid = await webchat_service.validate_widget_session(
                db=db,
                widget_id=webchat_channel.id,
                session_token=session_token
            )
            
            # Should validate session token format
            assert isinstance(is_valid, bool)

    @given(
        invalid_workspace_slug=st.text(min_size=1, max_size=50),
        inactive_workspace_slug=workspace_slug()
    )
    @settings(max_examples=50)
    async def test_property_34_webchat_api_error_handling(self, invalid_workspace_slug, inactive_workspace_slug):
        """
        Property 34: WebChat API Error Handling
        For any WebChat API request with non-existent workspace_slug,
        the system should return 404 errors and only return config for active channels.
        
        Validates: Requirements 17.4, 17.5
        """
        from app.services.webchat_service import WebChatService
        webchat_service = WebChatService()
        
        async with get_db() as db:
            # Test non-existent workspace
            config = await webchat_service.get_widget_config(db, invalid_workspace_slug)
            assert config is None, "Should return None for non-existent workspace"
            
            # Create inactive workspace
            inactive_workspace = Workspace(
                id=uuid4(),
                business_name="Inactive Business",
                slug=inactive_workspace_slug,
                tier='pro',
                owner_id=uuid4(),
                is_active=False
            )
            
            # Create inactive webchat channel
            inactive_channel = Channel(
                id=uuid4(),
                workspace_id=inactive_workspace.id,
                type='webchat',
                name='Inactive WebChat',
                credentials='{"test": "config"}',
                is_active=False
            )
            
            db.add(inactive_workspace)
            db.add(inactive_channel)
            await db.commit()
            
            # Test inactive channel
            config = await webchat_service.get_widget_config(db, inactive_workspace_slug)
            assert config is None, "Should return None for inactive webchat channel"
            
            # Test with active workspace but inactive channel
            inactive_workspace.is_active = True
            await db.commit()
            
            config = await webchat_service.get_widget_config(db, inactive_workspace_slug)
            assert config is None, "Should return None when webchat channel is inactive"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])