"""
Database Constraint Property Test for ChatSaaS Backend
Tests Property 31: Database Constraint Enforcement

**Validates: Requirements 14.2, 14.4, 14.6**

This test validates that the database properly enforces:
- Foreign key constraints
- Unique constraints  
- Vector column support with appropriate dimensions
- Timezone-aware timestamps using UTC storage
"""

import pytest
from hypothesis import given, strategies as st, settings as hypothesis_settings, HealthCheck
from uuid import uuid4
from datetime import datetime, timezone
import secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Import application modules
from app.database import Base
from app.models import User, Workspace, Channel, Contact, Conversation, Message, Document, DocumentChunk, Agent
from app.config import settings


class TestDatabaseConstraintProperties:
    """Property tests for database constraints and data integrity"""
    
    @given(
        vector_dimension=st.just(3072)  # Test with the configured dimension (3072 for Google Gemini)
    )
    @hypothesis_settings(max_examples=1, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=5000)
    @pytest.mark.asyncio
    async def test_property_31_database_constraint_enforcement(self, vector_dimension):
        """
        Property 31: Database Constraint Enforcement
        For any database operation, the system should enforce foreign key constraints 
        and unique constraints as defined in models, support vector columns with 
        appropriate dimensions, and handle timezone-aware timestamps using UTC storage.
        
        **Validates: Requirements 14.2, 14.4, 14.6**
        """
        # Create database session for this test
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Ensure all tables exist (idempotent — skips tables that already exist)
        from app.models import (  # noqa: F401
            user, workspace, channel, contact, conversation, message,
            agent, document, document_chunk, usage_counter,
            platform_setting, tier_change, rate_limit
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session() as db:
            try:
                # Test 1: Foreign Key Constraints
                # Create workspace without valid owner - should fail
                workspace = Workspace(
                    id=uuid4(),
                    name="Test Business",
                    slug=f"test-{secrets.token_hex(8)}",
                    tier="free",
                    owner_id=uuid4()  # This references non-existent user
                )
                
                db.add(workspace)
                with pytest.raises(IntegrityError) as exc_info:
                    await db.commit()
                assert "foreign key constraint" in str(exc_info.value).lower()
                await db.rollback()
                
                # Create valid user first, then workspace
                user = User(
                    id=uuid4(),
                    email=f"test-{secrets.token_hex(8)}@example.com",
                    hashed_password="$2b$12$test_hash",
                    is_active=True
                )
                db.add(user)
                await db.commit()
                
                # Store values for later use (before any rollbacks)
                user_id = user.id
                user_email = user.email
                
                workspace.owner_id = user_id
                db.add(workspace)
                await db.commit()
                
                # Store workspace values
                workspace_id = workspace.id
                workspace_slug = workspace.slug
                
                # Test 2: Unique Constraints
                # Test workspace slug uniqueness
                duplicate_workspace = Workspace(
                    id=uuid4(),
                    name="Another Business",
                    slug=workspace_slug,  # Same slug should fail
                    tier="free",
                    owner_id=user_id
                )
                db.add(duplicate_workspace)
                with pytest.raises(IntegrityError) as exc_info:
                    await db.commit()
                assert "unique constraint" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower()
                await db.rollback()
                
                # Test user email uniqueness
                duplicate_user = User(
                    id=uuid4(),
                    email=user_email,  # Same email should fail
                    hashed_password="$2b$12$another_hash",
                    is_active=True
                )
                db.add(duplicate_user)
                with pytest.raises(IntegrityError) as exc_info:
                    await db.commit()
                assert "unique constraint" in str(exc_info.value).lower() or "unique" in str(exc_info.value).lower()
                await db.rollback()
                
                # Test 3: Contact unique constraint (workspace_id, channel_id, external_id)
                channel = Channel(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    type="webchat",
                    is_active=True
                )
                db.add(channel)
                await db.commit()
                
                # Store channel ID
                channel_id = channel.id
                
                contact1 = Contact(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    external_id="user123",
                    name="Test User"
                )
                db.add(contact1)
                await db.commit()
                
                # Store contact ID
                contact1_id = contact1.id
                contact1_created_at = contact1.created_at
                
                # Duplicate contact should fail
                contact2 = Contact(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    external_id="user123",  # Same external_id in same workspace/channel
                    name="Another User"
                )
                db.add(contact2)
                with pytest.raises(IntegrityError) as exc_info:
                    await db.commit()
                assert "unique constraint" in str(exc_info.value).lower() or "uq_contact_per_channel" in str(exc_info.value)
                await db.rollback()
                
                # Test 4: Vector Column Support with Appropriate Dimensions
                # With PostgreSQL and pgvector, we can properly test vector dimensions
                document = Document(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    name="test.pdf",
                    file_path="/tmp/test.pdf",
                    status="completed"
                )
                db.add(document)
                await db.commit()
                
                # Store document values
                document_id = document.id
                document_created_at = document.created_at
                
                # Create vector embedding with specified dimension
                embedding_vector = [0.1] * vector_dimension
                
                chunk = DocumentChunk(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    document_id=document_id,
                    content="Test chunk content for vector embedding",
                    embedding=embedding_vector,
                    chunk_index=0
                )
                db.add(chunk)
                await db.commit()
                
                # Store chunk ID
                chunk_id = chunk.id
                
                # Verify vector was stored correctly
                result = await db.execute(
                    select(DocumentChunk).where(DocumentChunk.id == chunk_id)
                )
                stored_chunk = result.scalar_one()
                
                # Verify the embedding dimension matches what we stored
                assert len(stored_chunk.embedding) == vector_dimension
                
                # Test 5: Timezone-aware Timestamps Using UTC Storage
                # Verify all created_at timestamps are timezone-aware
                # Refresh objects to get latest data
                await db.refresh(user)
                await db.refresh(workspace)
                
                user_created_at = user.created_at
                workspace_created_at = workspace.created_at
                
                assert workspace_created_at.tzinfo is not None
                assert user_created_at.tzinfo is not None
                assert contact1_created_at.tzinfo is not None
                assert document_created_at.tzinfo is not None
                
                # Verify timestamps are recent (within last minute)
                utc_now = datetime.now(timezone.utc)
                time_diff = utc_now - workspace_created_at.replace(tzinfo=timezone.utc)
                assert time_diff.total_seconds() < 60  # Created within last minute
                
                # Test 6: Message External ID Unique Constraint (partial unique index)
                conversation = Conversation(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    contact_id=contact1_id,
                    channel_type="webchat",
                    status="active"
                )
                db.add(conversation)
                await db.commit()
                
                # Store conversation ID
                conversation_id = conversation.id
                
                # First message with external_message_id
                message1 = Message(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    role="customer",
                    content="Test message",
                    channel_type="webchat",
                    external_message_id="msg_123"
                )
                db.add(message1)
                await db.commit()
                
                # Duplicate external_message_id in same conversation should fail
                message2 = Message(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    role="customer", 
                    content="Another message",
                    channel_type="webchat",
                    external_message_id="msg_123"  # Same external ID
                )
                db.add(message2)
                with pytest.raises(IntegrityError) as exc_info:
                    await db.commit()
                assert "unique" in str(exc_info.value).lower()
                await db.rollback()
                
                # But NULL external_message_id should be allowed multiple times
                message3 = Message(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    role="ai",
                    content="AI response 1",
                    channel_type="webchat",
                    external_message_id=None
                )
                message4 = Message(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    role="ai",
                    content="AI response 2", 
                    channel_type="webchat",
                    external_message_id=None
                )
                db.add_all([message3, message4])
                await db.commit()  # Should succeed
                
                # Test 7: Agent Email Unique Constraint per Workspace
                agent1 = Agent(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    name="Agent One",
                    email="agent@example.com",
                    is_active=True
                )
                db.add(agent1)
                await db.commit()
                
                # Duplicate email in same workspace should fail
                agent2 = Agent(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    name="Agent Two",
                    email="agent@example.com",  # Same email
                    is_active=True
                )
                db.add(agent2)
                with pytest.raises(IntegrityError) as exc_info:
                    await db.commit()
                assert "unique constraint" in str(exc_info.value).lower() or "uq_agent_workspace_email" in str(exc_info.value)
                await db.rollback()
                
                # But same email in different workspace should be allowed
                workspace2 = Workspace(
                    id=uuid4(),
                    name="Another Business",
                    slug=f"another-{secrets.token_hex(8)}",
                    tier="free",
                    owner_id=user_id
                )
                db.add(workspace2)
                await db.commit()
                
                # Store workspace2 ID
                workspace2_id = workspace2.id
                
                agent3 = Agent(
                    id=uuid4(),
                    workspace_id=workspace2_id,  # Different workspace
                    name="Agent Three",
                    email="agent@example.com",  # Same email but different workspace
                    is_active=True
                )
                db.add(agent3)
                await db.commit()  # Should succeed
                
            finally:
                # Clean up: rollback any uncommitted changes
                await db.rollback()
                await engine.dispose()


if __name__ == "__main__":
    # Run property tests with verbose output
    pytest.main([__file__, "-v", "--tb=short"])
