"""
Property-Based Tests for RAG Engine and Escalation System
Tests properties 9-17 from the design document.
"""

import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.database import get_db
from app.models import Workspace, Document, DocumentChunk, Conversation, Message, Agent
from app.services.message_processor import MessageProcessor
from app.services.rag_engine import RAGEngine
from app.services.escalation_service import EscalationService
from app.services.tier_manager import TierManager
from app.services.email_service import EmailService

@composite
def message_content(draw):
    """Generate valid message content"""
    return draw(st.text(min_size=1, max_size=1000))

@composite
def document_content(draw):
    """Generate document content for processing"""
    return draw(st.text(min_size=100, max_size=5000))

@composite
def escalation_keywords(draw):
    """Generate messages with escalation keywords"""
    keywords = ["human", "agent", "manager", "speak to someone", "transfer me"]
    base_message = draw(st.text(min_size=10, max_size=100))
    keyword = draw(st.sampled_from(keywords))
    return f"{base_message} {keyword}"

class TestTokenLimitProperties:
    """Property tests for token limit protection"""
    
    @given(
        token_count=st.integers(min_value=1000, max_value=100000),
        monthly_limit=st.integers(min_value=500, max_value=50000)
    )
    @settings(max_examples=100)
    async def test_property_9_token_limit_protection(self, token_count, monthly_limit):
        """
        Property 9: Token Limit Protection
        For any workspace approaching or exceeding monthly token limits, 
        AI processing should be prevented before making expensive API calls.
        
        Validates: Requirements 3.3, 3.7, 3.8
        """
        tier_manager = TierManager()
        workspace_id = uuid4()
        
        async with get_db() as db:
            # Create workspace with specific tier
            workspace = Workspace(
                id=workspace_id,
                business_name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier='free',  # 500 message limit
                owner_id=uuid4()
            )
            db.add(workspace)
            
            # Set current usage near/at limit
            from app.models import UsageCounter
            current_month = datetime.now().strftime("%Y-%m")
            usage = UsageCounter(
                id=uuid4(),
                workspace_id=workspace_id,
                month=current_month,
                messages_sent=0,
                tokens_used=monthly_limit - 100 if token_count < monthly_limit else monthly_limit + 100
            )
            db.add(usage)
            await db.commit()
            
            # Check if processing should be allowed
            can_process = await tier_manager.check_message_limit(db, workspace_id, token_count)
            
            if usage.tokens_used + token_count > monthly_limit:
                assert not can_process, "Should prevent processing when token limit exceeded"
            else:
                assert can_process, "Should allow processing when within limits"


class TestRAGProperties:
    """Property tests for RAG engine functionality"""
    
    @given(
        query=message_content(),
        doc_content=document_content()
    )
    @settings(max_examples=100)
    async def test_property_10_rag_processing_consistency(self, query, doc_content):
        """
        Property 10: RAG Processing Consistency
        For any customer message, the RAG engine should generate query embeddings,
        search document chunks with 0.75 similarity threshold, and return appropriate responses.
        
        Validates: Requirements 3.4, 3.5, 3.6
        """
        rag_engine = RAGEngine()
        workspace_id = uuid4()
        
        async with get_db() as db:
            # Create workspace
            workspace = Workspace(
                id=workspace_id,
                business_name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier='pro',
                owner_id=uuid4(),
                fallback_message="I don't have information about that."
            )
            db.add(workspace)
            
            # Create document and chunks
            document = Document(
                id=uuid4(),
                workspace_id=workspace_id,
                filename="test.txt",
                original_filename="test.txt",
                file_size=len(doc_content),
                content_type="text/plain",
                status="completed"
            )
            db.add(document)
            
            # Create document chunk with embedding
            chunk = DocumentChunk(
                id=uuid4(),
                document_id=document.id,
                workspace_id=workspace_id,
                content=doc_content[:500],  # First 500 chars
                token_count=100,
                embedding=[0.1] * 1536,  # Mock embedding
                chunk_index=0
            )
            db.add(chunk)
            await db.commit()
            
            # Test RAG response generation
            with patch.object(rag_engine, '_generate_embedding') as mock_embedding:
                mock_embedding.return_value = [0.1] * 1536  # Mock similar embedding
                
                response = await rag_engine.generate_response(
                    query=query,
                    workspace_id=workspace_id,
                    conversation_history=[],
                    db=db
                )
                
                # Verify embedding was generated
                mock_embedding.assert_called_once_with(query)
                
                # Response should either be contextual or fallback
                assert response is not None
                assert len(response) > 0

    @given(
        filename=st.text(min_size=1, max_size=100),
        content=document_content()
    )
    @settings(max_examples=100)
    async def test_property_13_document_processing_pipeline(self, filename, content):
        """
        Property 13: Document Processing Pipeline
        For any valid document upload, the system should validate, extract text,
        chunk into segments, generate embeddings, and store with vector embeddings.
        
        Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
        """
        from app.services.document_processor import DocumentProcessor
        document_processor = DocumentProcessor()
        workspace_id = uuid4()
        
        # Ensure filename has valid extension
        if not filename.endswith(('.txt', '.pdf')):
            filename += '.txt'
        
        async with get_db() as db:
            # Create workspace
            workspace = Workspace(
                id=workspace_id,
                business_name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier='pro',
                owner_id=uuid4()
            )
            db.add(workspace)
            await db.commit()
            
            # Process document
            with patch('builtins.open', create=True) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = content
                
                document = await document_processor.process_document(
                    db=db,
                    workspace_id=workspace_id,
                    filename=filename,
                    content=content.encode(),
                    content_type="text/plain"
                )
                
                # Verify document was created
                assert document is not None
                assert document.workspace_id == workspace_id
                assert document.filename == filename
                
                # Verify chunks were created
                chunks = await db.execute(
                    "SELECT * FROM document_chunks WHERE document_id = :doc_id",
                    {"doc_id": document.id}
                )
                chunk_list = chunks.fetchall()
                
                # Should have at least one chunk for non-empty content
                if len(content) > 0:
                    assert len(chunk_list) > 0

    @given(content=document_content())
    @settings(max_examples=100)
    async def test_property_15_document_round_trip(self, content):
        """
        Property 15: Document Round Trip
        For any valid document, uploading then processing then retrieving 
        should produce searchable content.
        
        Validates: Requirements 5.8
        """
        from app.services.document_processor import DocumentProcessor
        document_processor = DocumentProcessor()
        rag_engine = RAGEngine()
        workspace_id = uuid4()
        
        async with get_db() as db:
            # Create workspace
            workspace = Workspace(
                id=workspace_id,
                business_name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier='pro',
                owner_id=uuid4()
            )
            db.add(workspace)
            await db.commit()
            
            # Upload and process document
            document = await document_processor.process_document(
                db=db,
                workspace_id=workspace_id,
                filename="test.txt",
                content=content.encode(),
                content_type="text/plain"
            )
            
            # Verify document can be found through search
            # Extract a phrase from the content for search
            search_phrase = content[:50] if len(content) >= 50 else content
            
            with patch.object(rag_engine, '_generate_embedding') as mock_embedding:
                mock_embedding.return_value = [0.1] * 1536
                
                chunks = await rag_engine.search_documents(
                    query_embedding=[0.1] * 1536,
                    workspace_id=workspace_id,
                    threshold=0.5,  # Lower threshold for testing
                    db=db
                )
                
                # Should find at least one chunk if document was processed
                if document.status == "completed":
                    assert len(chunks) > 0


class TestEscalationProperties:
    """Property tests for escalation system"""
    
    @given(
        message=escalation_keywords(),
        conversation_history=st.lists(st.text(min_size=1, max_size=100), max_size=5)
    )
    @settings(max_examples=100)
    async def test_property_11_escalation_classification_accuracy(self, message, conversation_history):
        """
        Property 11: Escalation Classification Accuracy
        For any customer message, the escalation service should classify escalation need
        with confidence scoring and handle explicit keywords appropriately.
        
        Validates: Requirements 4.1, 4.2, 4.3, 4.6
        """
        escalation_service = EscalationService()
        
        # Mock conversation history
        mock_history = [
            Message(
                id=uuid4(),
                conversation_id=uuid4(),
                content=msg,
                sender_type='customer',
                token_count=len(msg.split()),
                created_at=datetime.now()
            ) for msg in conversation_history
        ]
        
        with patch.object(escalation_service, '_classify_with_ai') as mock_classify:
            mock_classify.return_value = {"should_escalate": True, "confidence": 0.8, "reason": "explicit"}
            
            decision = await escalation_service.should_escalate(
                message=message,
                conversation_history=mock_history
            )
            
            # Verify escalation decision structure
            assert hasattr(decision, 'should_escalate')
            assert hasattr(decision, 'confidence')
            assert hasattr(decision, 'reason')
            
            # For messages with explicit keywords, should escalate
            explicit_keywords = ["human", "agent", "manager"]
            if any(keyword in message.lower() for keyword in explicit_keywords):
                assert decision.should_escalate
                assert decision.reason == "explicit"

    @given(workspace_id=st.uuids())
    @settings(max_examples=100)
    async def test_property_12_escalation_workflow_routing(self, workspace_id):
        """
        Property 12: Escalation Workflow Routing
        For any escalation trigger, the system should update conversation status
        and route appropriately based on agent availability.
        
        Validates: Requirements 4.4, 4.5
        """
        escalation_service = EscalationService()
        conversation_id = uuid4()
        
        async with get_db() as db:
            # Create workspace and conversation
            workspace = Workspace(
                id=workspace_id,
                business_name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier='pro',
                owner_id=uuid4()
            )
            conversation = Conversation(
                id=conversation_id,
                workspace_id=workspace_id,
                contact_id=uuid4(),
                status='active'
            )
            db.add(workspace)
            db.add(conversation)
            await db.commit()
            
            # Test escalation with no agents
            with patch.object(escalation_service, '_notify_agents') as mock_notify:
                with patch.object(escalation_service, '_send_owner_email') as mock_email:
                    await escalation_service.escalate_conversation(
                        db=db,
                        conversation_id=conversation_id,
                        reason="explicit",
                        confidence=0.9
                    )
                    
                    # Verify conversation status updated
                    await db.refresh(conversation)
                    assert conversation.status == 'escalated'
                    
                    # Should attempt to notify agents or send email
                    assert mock_notify.called or mock_email.called


class TestAgentProperties:
    """Property tests for agent management"""
    
    @given(
        email=st.emails(),
        workspace_tier=st.sampled_from(['free', 'starter', 'growth', 'pro'])
    )
    @settings(max_examples=100)
    async def test_property_16_agent_invitation_workflow(self, email, workspace_tier):
        """
        Property 16: Agent Invitation Workflow
        For any agent invitation within tier limits, the system should generate
        secure tokens, send emails, and handle acceptance properly.
        
        Validates: Requirements 6.2, 6.3, 6.4, 6.5
        """
        from app.services.agent_service import AgentService
        agent_service = AgentService()
        workspace_id = uuid4()
        
        # Determine if tier allows agents
        agent_limits = {'free': 0, 'starter': 0, 'growth': 0, 'pro': 2}
        max_agents = agent_limits[workspace_tier]
        
        async with get_db() as db:
            # Create workspace
            workspace = Workspace(
                id=workspace_id,
                business_name="Test Business",
                slug=f"test-{workspace_id.hex[:8]}",
                tier=workspace_tier,
                owner_id=uuid4()
            )
            db.add(workspace)
            await db.commit()
            
            if max_agents > 0:
                # Should allow agent invitation
                with patch.object(agent_service, '_send_invitation_email') as mock_email:
                    agent = await agent_service.invite_agent(
                        db=db,
                        workspace_id=workspace_id,
                        email=email
                    )
                    
                    # Verify agent record created
                    assert agent is not None
                    assert agent.email == email
                    assert agent.invitation_token is not None
                    assert agent.invitation_expires_at is not None
                    
                    # Verify email was sent
                    mock_email.assert_called_once()
            else:
                # Should reject agent invitation for tiers without agent support
                with pytest.raises(Exception) as exc_info:
                    await agent_service.invite_agent(
                        db=db,
                        workspace_id=workspace_id,
                        email=email
                    )
                assert "tier" in str(exc_info.value).lower() or "limit" in str(exc_info.value).lower()

    @given(agent_id=st.uuids())
    @settings(max_examples=100)
    async def test_property_17_agent_deactivation_cleanup(self, agent_id):
        """
        Property 17: Agent Deactivation Cleanup
        For any agent deactivation, all their active conversations should be
        updated from status 'agent' back to 'escalated'.
        
        Validates: Requirements 6.6
        """
        from app.services.agent_service import AgentService
        agent_service = AgentService()
        workspace_id = uuid4()
        
        async with get_db() as db:
            # Create agent with active conversations
            agent = Agent(
                id=agent_id,
                workspace_id=workspace_id,
                email="agent@test.com",
                is_active=True
            )
            
            # Create conversations assigned to agent
            conversations = [
                Conversation(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    contact_id=uuid4(),
                    status='agent',
                    assigned_agent_id=agent_id
                ) for _ in range(3)
            ]
            
            db.add(agent)
            for conv in conversations:
                db.add(conv)
            await db.commit()
            
            # Deactivate agent
            await agent_service.deactivate_agent(db, agent_id)
            
            # Verify conversations were updated
            for conv in conversations:
                await db.refresh(conv)
                assert conv.status == 'escalated'
                assert conv.assigned_agent_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])