"""
Database Constraint Property Test for ChatSaaS Backend
Tests Property 31: Database Constraint Enforcement

This test validates that the database properly enforces:
- Foreign key constraints
- Unique constraints  
- Vector column support with appropriate dimensions
- Timezone-aware timestamps using UTC storage
"""

import pytest
import asyncio
from hypothesis import given, strategies as st, settings
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import secrets
import numpy as np
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

# Import application modules
from app.database import get_db
from app.models import User, Workspace, Channel, Contact, Conversation, Message, Document, DocumentChunk, Agent
from app.config import settings as app_settings

# Test configuration
test_settings = app_settings


class TestDatabaseConstraintProperties:
    """Property tests for database constraints and data integrity"""
    
    @given(
        workspace_count=st.integers(min_value=1, max_value=3),
        contact_count=st.integers(min_value=1, max_value=5),
        vector_dimension=st.sampled_from([1536, 3072])  # OpenAI vs Google dimensions
    )
    @settings(max_examples=1)  # Keep minimal for speed as requested
    @pytest.mark.asyncio
    async def test_property_31_database_constraint_enforcement(self, workspace_count, contact_count, vector_dimension, db_session):
        """
        Property 31: Database Constraint Enforcement
        For any database operation, the system should enforce foreign key constraints 
        and unique constraints as defined in models, support vector columns with 
        appropriate dimensions, and handle timezone-aware timestamps using UTC storage.
        
        Validates: Requirements 14.2, 14.4, 14.6
        """
        db = db_session
            # Test 1: Foreign Key Constraints
            # Create valid workspace first
            workspace = Workspace(
                id=uuid4(),
                business_name="Test Business",
                slug=f"test-{secrets.token_hex(8)}",
                tier="free",
                owner_id=uuid4()  # This should reference a valid user, but we'll test FK constraint
            )
            
            # Test foreign key constraint violation - should fail
            db.add(workspace)
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            assert "foreign key constraint" in str(exc_info.value).lower()
            await db.rollback()
            
            # Create valid user first, then workspace
            user = User(
                id=uuid4(),
                email=f"test-{secrets.token_hex(8)}@example.com",
                password_hash="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.commit()
            
            workspace.owner_id = user.id
            db.add(workspace)
            await db.commit()
            
            # Test 2: Unique Constraints
            # Test workspace slug uniqueness
            duplicate_workspace = Workspace(
                id=uuid4(),
                business_name="Another Business",
                slug=workspace.slug,  # Same slug should fail
                tier="free",
                owner_id=user.id
            )
            db.add(duplicate_workspace)
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            assert "unique constraint" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test user email uniqueness
            duplicate_user = User(
                id=uuid4(),
                email=user.email,  # Same email should fail
                password_hash="$2b$12$another_hash",
                is_active=True
            )
            db.add(duplicate_user)
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            assert "unique constraint" in str(exc_info.value).lower()
            await db.rollback()
            
            # Test 3: Contact unique constraint (workspace_id, channel_id, external_id)
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace.id,
                type="webchat",
                name="Test Channel",
                credentials="encrypted_test"
            )
            db.add(channel)
            await db.commit()
            
            contact1 = Contact(
                id=uuid4(),
                workspace_id=workspace.id,
                channel_id=channel.id,
                external_id="user123",
                name="Test User"
            )
            db.add(contact1)
            await db.commit()
            
            # Duplicate contact should fail
            contact2 = Contact(
                id=uuid4(),
                workspace_id=workspace.id,
                channel_id=channel.id,
                external_id="user123",  # Same external_id in same workspace/channel
                name="Another User"
            )
            db.add(contact2)
            with pytest.raises(IntegrityError) as exc_info:
                await db.commit()
            assert "unique constraint" in str(exc_info.value).lower() or "uq_contact_per_channel" in str(exc_info.value)
            await db.rollback()
            
            # Test 4: Vector Column Support with Appropriate Dimensions
            document = Document(
                id=uuid4(),
                workspace_id=workspace.id,
                filename="test.pdf",
                original_filename="test.pdf",
                file_size=1024,
                content_type="application/pdf",
                status="completed"
            )
            db.add(document)
            await db.commit()
            
            # Create vector embedding with specified dimension
            embedding_vector = np.random.rand(vector_dimension).tolist()
            
            chunk = DocumentChunk(
                id=uuid4(),
                workspace_id=workspace.id,
                document_id=document.id,
                content="Test chunk content for vector embedding",
                token_count=10,
                embedding=embedding_vector,
                chunk_index=0
            )
            db.add(chunk)
            await db.commit()
            
            # Verify vector was stored correctly
            result = await db.execute(
                select(DocumentChunk).where(DocumentChunk.id == chunk.id)
            )
            stored_chunk = result.scalar_one()
            assert len(stored_chunk.embedding) == vector_dimension
            
            # Test wrong dimension should fail (if we try to insert incompatible dimension)
            wrong_dimension = 512 if vector_dimension != 512 else 256
            wrong_embedding = np.random.rand(wrong_dimension).tolist()
            
            wrong_chunk = DocumentChunk(
                id=uuid4(),
                workspace_id=workspace.id,
                document_id=document.id,
                content="Wrong dimension chunk",
                token_count=10,
                embedding=wrong_embedding,
                chunk_index=1
            )
            db.add(wrong_chunk)
            
            # This should fail due to dimension mismatch with the vector column definition
            with pytest.raises(Exception):  # Could be IntegrityError or other DB error
                await db.commit()
            await db.rollback()
            
            # Test 5: Timezone-aware Timestamps Using UTC Storage
            # Verify all created_at timestamps are timezone-aware and in UTC
            assert workspace.created_at.tzinfo is not None
            assert user.created_at.tzinfo is not None
            assert contact1.created_at.tzinfo is not None
            assert document.created_at.tzinfo is not None
            assert chunk.created_at.tzinfo is not None
            
            # Verify timestamps are stored as UTC (or at least timezone-aware)
            # The exact timezone depends on database configuration, but should be consistent
            utc_now = datetime.now(timezone.utc)
            
            # All timestamps should be recent (within last minute) and timezone-aware
            time_diff = utc_now - workspace.created_at.replace(tzinfo=timezone.utc)
            assert time_diff.total_seconds() < 60  # Created within last minute
            
            # Test 6: Message External ID Unique Constraint (partial unique index)
            conversation = Conversation(
                id=uuid4(),
                workspace_id=workspace.id,
                contact_id=contact1.id,
                status="active"
            )
            db.add(conversation)
            await db.commit()
            
            # First message with external_message_id
            message1 = Message(
                id=uuid4(),
                conversation_id=conversation.id,
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
                conversation_id=conversation.id,
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
                conversation_id=conversation.id,
                role="ai",
                content="AI response 1",
                channel_type="webchat",
                external_message_id=None
            )
            message4 = Message(
                id=uuid4(),
                conversation_id=conversation.id,
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
                workspace_id=workspace.id,
                name="Agent One",
                email="agent@example.com",
                is_active=True
            )
            db.add(agent1)
            await db.commit()
            
            # Duplicate email in same workspace should fail
            agent2 = Agent(
                id=uuid4(),
                workspace_id=workspace.id,
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
                business_name="Another Business",
                slug=f"another-{secrets.token_hex(8)}",
                tier="free",
                owner_id=user.id
            )
            db.add(workspace2)
            await db.commit()
            
            agent3 = Agent(
                id=uuid4(),
                workspace_id=workspace2.id,  # Different workspace
                name="Agent Three",
                email="agent@example.com",  # Same email but different workspace
                is_active=True
            )
            db.add(agent3)
            await db.commit()  # Should succeed


if __name__ == "__main__":
    # Run property tests with verbose output
    pytest.main([__file__, "-v", "--tb=short"])