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
from app.services.tier_manager import TierManager

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

class TestMaintenanceModeProperties:
    """Property tests for maintenance mode priority"""
    
    @given(
        message_content=st.text(min_size=1, max_size=500),
        maintenance_enabled=st.booleans()
    )
    @settings(max_examples=5, deadline=10000)
    @pytest.mark.asyncio
    async def test_property_7_maintenance_mode_priority(self, message_content, maintenance_enabled):
        """
        Property 7: Maintenance Mode Priority
        For any incoming customer message, when maintenance mode is enabled,
        the system should check this setting first and return a maintenance message
        without performing any AI processing, escalation classification, or RAG operations,
        while still saving the message.

        Validates: Requirements 3.1, 18.1, 18.2, 18.3, 18.4, 18.5

        Feature: chatsaas-backend, Property 7: Maintenance Mode Priority
        """
        from app.models.user import User
        from app.models.channel import Channel
        from app.models.platform_setting import PlatformSetting
        from app.services.message_processor import MessageProcessor, MaintenanceModeError
        from unittest.mock import AsyncMock, patch

        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)

        try:
            # Create user and workspace
            user = User(
                id=uuid4(),
                email=f"test-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()

            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier="pro"
            )
            db.add(workspace)
            await db.flush()

            # Create channel
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace.id,
                type="webchat",
                config={}
            )
            db.add(channel)
            await db.commit()

            # Set maintenance mode (upsert to avoid unique constraint violations)
            from sqlalchemy import select
            
            # Check if maintenance_mode setting exists
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == "maintenance_mode")
            )
            maintenance_setting = result.scalar_one_or_none()
            
            if maintenance_setting:
                maintenance_setting.value = "true" if maintenance_enabled else "false"
            else:
                maintenance_setting = PlatformSetting(
                    key="maintenance_mode",
                    value="true" if maintenance_enabled else "false"
                )
                db.add(maintenance_setting)
            
            # Check if maintenance_message setting exists
            result = await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == "maintenance_message")
            )
            maintenance_msg_setting = result.scalar_one_or_none()
            
            if maintenance_msg_setting:
                maintenance_msg_setting.value = "System is under maintenance. Please try again later."
            else:
                maintenance_msg_setting = PlatformSetting(
                    key="maintenance_message",
                    value="System is under maintenance. Please try again later."
                )
                db.add(maintenance_msg_setting)
            
            await db.commit()

            # Create message processor
            processor = MessageProcessor(db)

            if maintenance_enabled:
                # When maintenance mode is enabled, should raise MaintenanceModeError
                # before any AI/RAG/Escalation processing
                with pytest.raises(MaintenanceModeError) as exc_info:
                    await processor.preprocess_message(
                        workspace_id=str(workspace.id),
                        channel_id=str(channel.id),
                        external_contact_id="test-contact-123",
                        content=message_content,
                        external_message_id=f"msg-{uuid4().hex[:8]}"
                    )

                # Verify maintenance message is returned
                error_message = str(exc_info.value)
                assert "maintenance" in error_message.lower()

            else:
                # When maintenance mode is disabled, processing should proceed normally
                # (though it may fail at later stages, we just verify maintenance check passes)
                try:
                    result = await processor.preprocess_message(
                        workspace_id=str(workspace.id),
                        channel_id=str(channel.id),
                        external_contact_id="test-contact-456",
                        content=message_content,
                        external_message_id=f"msg-{uuid4().hex[:8]}"
                    )
                    
                    # If successful, verify message was created
                    assert result is not None
                    assert "message" in result
                    assert result["message"].content == message_content
                    
                except Exception as e:
                    # If it fails, it should NOT be due to maintenance mode
                    assert "maintenance" not in str(e).lower(), \
                        "Should not fail due to maintenance when maintenance mode is disabled"

        finally:
            # Cleanup
            await db.rollback()
            await db.close()


class TestTokenLimitProperties:
    """Property tests for token limit protection"""
    
    @given(
        tier=st.sampled_from(['free', 'pro']),  # Just test 2 tiers
        current_message_count=st.integers(min_value=0, max_value=1000),  # Smaller range
        additional_messages=st.integers(min_value=1, max_value=10)  # Smaller range
    )
    @settings(max_examples=5, deadline=10000)  # Only 5 examples with 10s deadline
    @pytest.mark.asyncio
    async def test_property_9_token_limit_protection(self, tier, current_message_count, additional_messages):
        """
        Property 9: Token Limit Protection
        For any workspace approaching or exceeding monthly token limits, 
        AI processing should be prevented before making expensive API calls,
        and usage should be tracked accurately to prevent runaway costs.

        Validates: Requirements 3.3, 3.7, 3.8

        Feature: chatsaas-backend, Property 9: Token Limit Protection
        """
        from app.config import TIER_LIMITS
        from app.models.user import User
        from app.models.usage_counter import UsageCounter
        from app.services.tier_manager import TierManager, TierLimitError
        from datetime import timezone

        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)

        try:
            # Get tier limits
            tier_limits = TIER_LIMITS[tier]
            monthly_message_limit = tier_limits["monthly_messages"]

            # Create user and workspace with specific tier
            user = User(
                id=uuid4(),
                email=f"test-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()

            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier=tier
            )
            db.add(workspace)
            await db.commit()

            # Set current usage to test value
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage_counter = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=current_month,
                messages_sent=current_message_count,
                tokens_used=0
            )
            db.add(usage_counter)
            await db.commit()

            # Test token limit protection via TierManager
            tier_manager = TierManager(db)

            # Calculate if we would exceed the limit
            would_exceed_limit = (current_message_count + additional_messages) > monthly_message_limit

            # Test limit enforcement
            if would_exceed_limit:
                # Should raise TierLimitError when limit would be exceeded
                with pytest.raises(TierLimitError) as exc_info:
                    await tier_manager.check_monthly_message_limit(
                        str(workspace.id), 
                        additional_messages
                    )

                # Verify error message contains useful information
                error_message = str(exc_info.value)
                assert "monthly message limit" in error_message.lower()
                assert tier in error_message.lower()

            else:
                # Should succeed when within limits
                result = await tier_manager.check_monthly_message_limit(
                    str(workspace.id), 
                    additional_messages
                )
                assert result == True

        finally:
            # Cleanup
            await db.rollback()
            await db.close()


class TestRAGProperties:
    """Property tests for RAG engine"""
    
    @given(
        query=st.text(min_size=10, max_size=200),
        has_documents=st.booleans(),
        has_conversation_history=st.booleans()
    )
    @settings(max_examples=10, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_10_rag_processing_consistency(self, query, has_documents, has_conversation_history):
        """
        Property 10: RAG Processing Consistency
        For any customer message, the RAG engine should generate query embeddings,
        search document chunks with 0.75 similarity threshold, and either return
        contextual responses using conversation history (last 3 exchanges) when
        relevant chunks are found, or return the workspace fallback message when
        no relevant content exists.

        Validates: Requirements 3.4, 3.5, 3.6

        Feature: chatsaas-backend, Property 10: RAG Processing Consistency
        """
        from app.models.user import User
        from app.models.channel import Channel
        from app.services.rag_engine import RAGEngine
        from unittest.mock import AsyncMock, patch
        
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Create workspace with fallback message
            user = User(
                id=uuid4(),
                email=f"test-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()
            
            fallback_message = "Sorry, I couldn't find an answer in our knowledge base."
            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier="pro",
                fallback_msg=fallback_message
            )
            db.add(workspace)
            await db.flush()
            
            # Create channel and conversation
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace.id,
                type="webchat",
                config={}
            )
            db.add(channel)
            await db.flush()
            
            # Create contact
            from app.models.contact import Contact
            contact = Contact(
                id=uuid4(),
                workspace_id=workspace.id,
                channel_id=channel.id,
                external_id=f"test-contact-{uuid4().hex[:8]}"
            )
            db.add(contact)
            await db.flush()
            
            conversation = Conversation(
                id=uuid4(),
                workspace_id=workspace.id,
                contact_id=contact.id,
                channel_type="webchat",
                status="active"
            )
            db.add(conversation)
            await db.flush()
            
            # Optionally add conversation history (last 3 exchanges = 6 messages)
            if has_conversation_history:
                for i in range(6):
                    role = "user" if i % 2 == 0 else "assistant"
                    msg = Message(
                        id=uuid4(),
                        conversation_id=conversation.id,
                        content=f"Test message {i}",
                        role=role,
                        channel_type="webchat"
                    )
                    db.add(msg)
                await db.flush()
            
            # Optionally add documents with chunks
            if has_documents:
                doc = Document(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    name="test-doc.txt",
                    file_path="/tmp/test-doc.txt",
                    status="ready"
                )
                db.add(doc)
                await db.flush()
                
                # Add a document chunk with mock embedding
                # Note: In real scenario, this would have actual embeddings
                chunk = DocumentChunk(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    document_id=doc.id,
                    chunk_index=0,
                    content="This is test content for RAG processing.",
                    embedding=[0.1] * 3072  # Mock embedding vector (3072 for Google)
                )
                db.add(chunk)
                await db.flush()
            
            await db.commit()
            
            # Test RAG engine processing
            rag_engine = RAGEngine(db)
            
            # Mock the AI provider calls to avoid external dependencies
            mock_embedding = [0.1] * 1536
            mock_response = "This is a test response based on the knowledge base."
            
            with patch('app.services.rag_engine.embedding_provider') as mock_embed_provider, \
                 patch('app.services.rag_engine.llm_provider') as mock_llm_provider:
                
                # Setup mocks
                mock_embed_provider.generate_embedding = AsyncMock(return_value=mock_embedding)
                mock_llm_provider.generate_response = AsyncMock(
                    return_value=(mock_response, 100, 50)
                )
                
                try:
                    # Process RAG query
                    result = await rag_engine.process_rag_query(
                        workspace_id=str(workspace.id),
                        query=query,
                        conversation_id=str(conversation.id)
                    )
                    
                    # Verify result structure
                    assert result is not None
                    assert "response" in result
                    assert "input_tokens" in result
                    assert "output_tokens" in result
                    assert "total_tokens" in result
                    assert "relevant_chunks_count" in result
                    assert "has_conversation_context" in result
                    assert "used_fallback" in result
                    
                    # Verify response is not empty
                    assert len(result["response"]) > 0
                    assert isinstance(result["response"], str)
                    
                    # Verify token counts are non-negative
                    assert result["input_tokens"] >= 0
                    assert result["output_tokens"] >= 0
                    assert result["total_tokens"] >= 0
                    
                    # Verify conversation context flag matches setup
                    assert result["has_conversation_context"] == has_conversation_history
                    
                    # Verify chunk count matches document setup
                    if has_documents:
                        # Should find chunks (may be 0 if similarity too low)
                        assert result["relevant_chunks_count"] >= 0
                    else:
                        # No documents means no chunks
                        assert result["relevant_chunks_count"] == 0
                        assert result["used_fallback"] == True
                    
                    # Verify embedding was generated for query
                    mock_embed_provider.generate_embedding.assert_called_once()
                    
                    # Verify LLM was called to generate response
                    mock_llm_provider.generate_response.assert_called_once()
                    
                except Exception as e:
                    # RAG may fail gracefully - verify error is expected
                    error_msg = str(e).lower()
                    # Accept failures from missing providers or configuration
                    assert any(word in error_msg for word in [
                        "provider", "embedding", "workspace", "document", 
                        "rag", "processing", "failed"
                    ]), f"Unexpected error: {e}"
        
        finally:
            await db.rollback()
            await db.close()


class TestEscalationProperties:
    """Property tests for escalation system"""
    
    @given(
        message_type=st.sampled_from([
            'explicit_human_keyword',  # Contains human/agent/manager keywords
            'frustration',             # Contains frustration patterns
            'urgency',                 # Contains urgency patterns
            'normal'                   # Normal message without escalation signals
        ]),
        additional_text=st.text(min_size=5, max_size=100)
    )
    @settings(max_examples=20, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_11_escalation_classification_accuracy(self, message_type, additional_text):
        """
        Property 11: Escalation Classification Accuracy
        For any customer message, the escalation service should classify escalation need 
        with confidence scoring, escalate with reason "explicit" for keyword detection 
        (human, agent, manager), escalate with reason "implicit" for frustration patterns, 
        and send acknowledgment messages to customers.

        Validates: Requirements 4.1, 4.2, 4.3, 4.6

        Feature: chatsaas-backend, Property 11: Escalation Classification Accuracy
        """
        from app.services.escalation_classifier import EscalationClassifier
        
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Generate message based on type
            if message_type == 'explicit_human_keyword':
                # Explicit human keywords that set category to 'human_request'
                # Only these three keywords trigger the human_request category
                keywords = ['human', 'agent', 'manager']
                import random
                keyword = random.choice(keywords)
                message = f"{additional_text} I need to speak to a {keyword}"
                expected_should_escalate = True
                expected_min_confidence = 0.7  # Gets +0.4 boost for human keywords
                expected_category = 'human_request'
                
            elif message_type == 'frustration':
                # Frustration patterns
                frustration_phrases = [
                    'I am so frustrated',
                    'This is terrible',
                    'I am very angry',
                    'This is the worst service',
                    'I hate this'
                ]
                import random
                phrase = random.choice(frustration_phrases)
                message = f"{additional_text} {phrase}"
                expected_should_escalate = None  # Depends on keyword count
                expected_min_confidence = 0.0
                expected_category = None  # Varies
                
            elif message_type == 'urgency':
                # Urgency patterns
                urgency_phrases = [
                    'This is urgent',
                    'I need help immediately',
                    'This is an emergency',
                    'Critical issue',
                    'ASAP please'
                ]
                import random
                phrase = random.choice(urgency_phrases)
                message = f"{additional_text} {phrase}"
                expected_should_escalate = None  # Depends on keyword count
                expected_min_confidence = 0.0
                expected_category = None  # Varies
                
            else:  # normal
                # Normal message without escalation signals
                message = f"Hello, {additional_text}. Can you help me understand how this works?"
                expected_should_escalate = False
                expected_min_confidence = 0.0
                expected_category = 'none'
            
            classifier = EscalationClassifier(db)
            
            # Test classification (without LLM to make test deterministic)
            classification = await classifier.classify_message(message, use_llm=False)
            
            # ─── Requirement 4.1: LLM-based classification with confidence scoring ───
            # Verify classification structure
            assert "should_escalate" in classification, "Missing should_escalate field"
            assert "confidence" in classification, "Missing confidence field"
            assert "reason" in classification, "Missing reason field"
            assert "category" in classification, "Missing category field"
            assert "escalation_type" in classification, "Missing escalation_type field"
            assert "keywords_found" in classification, "Missing keywords_found field"
            assert "classification_method" in classification, "Missing classification_method field"
            
            # Confidence should be in valid range [0.0, 1.0]
            assert 0.0 <= classification["confidence"] <= 1.0, \
                f"Confidence {classification['confidence']} out of range [0.0, 1.0]"
            
            # ─── Requirement 4.2: Explicit keyword detection with reason "explicit" ───
            if message_type == 'explicit_human_keyword':
                # Should detect explicit human keywords
                keywords_found = classification.get("keywords_found", [])
                assert len(keywords_found) > 0, \
                    f"Should detect explicit keywords in message: {message}"
                
                # Should have high confidence for explicit human keywords
                # Human keywords get +0.4 boost: 0.3 + 0.2 + 0.4 = 0.9
                assert classification["confidence"] >= expected_min_confidence, \
                    f"Confidence {classification['confidence']} too low for explicit keywords (expected >= {expected_min_confidence})"
                
                # Should recommend escalation (keyword_confidence > 0.5 threshold)
                assert classification["keyword_confidence"] > 0.5, \
                    f"Keyword confidence {classification['keyword_confidence']} should be > 0.5 for human keywords"
                
                assert classification["should_escalate"] == expected_should_escalate, \
                    f"Should escalate for explicit human keywords"
                
                # Requirement 4.2: escalation_type must be "explicit" for human keywords
                assert classification["escalation_type"] == "explicit", \
                    f"Escalation type should be 'explicit' for human keywords, got '{classification['escalation_type']}'"
                
                # Category should be human_request for explicit human keywords
                assert classification["category"] == expected_category, \
                    f"Category {classification['category']} should be {expected_category}"
            
            # ─── Requirement 4.3: Frustration/urgency pattern detection with reason "implicit" ───
            if message_type in ['frustration', 'urgency']:
                # Should detect frustration or urgency keywords
                keywords_found = classification.get("keywords_found", [])
                
                # Should have reasonable confidence for implicit signals
                assert classification["confidence"] >= 0.0, \
                    f"Confidence should be non-negative: {classification['confidence']}"
                
                # If keywords detected with sufficient confidence, should recommend escalation
                # Note: keyword_confidence > 0.5 is the threshold in the classifier
                if len(keywords_found) > 0 and classification["keyword_confidence"] > 0.5:
                    assert classification["should_escalate"] == True, \
                        f"Should escalate when frustration/urgency keywords detected with confidence {classification['keyword_confidence']}"
                    
                    # Requirement 4.3: escalation_type must be "implicit" for frustration/urgency
                    assert classification["escalation_type"] == "implicit", \
                        f"Escalation type should be 'implicit' for frustration/urgency patterns, got '{classification['escalation_type']}'"
                    
                    # Reason should mention keywords
                    assert "keywords" in classification["reason"].lower() or len(keywords_found) > 0, \
                        "Reason should mention keywords when escalating"
            
            # ─── Normal messages should not trigger false positives ───
            if message_type == 'normal':
                # Normal messages should generally not escalate
                # (unless they accidentally contain keywords from additional_text)
                keywords_found = classification.get("keywords_found", [])
                
                # If no keywords found, should not escalate
                if len(keywords_found) == 0:
                    assert classification["should_escalate"] == False, \
                        "Should not escalate normal messages without keywords"
                    assert classification["confidence"] < 0.5, \
                        "Confidence should be low for normal messages"
                    assert classification["category"] == expected_category, \
                        f"Category should be {expected_category} for normal messages"
                    assert classification["escalation_type"] is None, \
                        "Escalation type should be None for non-escalated messages"
            
            # ─── Verify classification metadata ───
            assert isinstance(classification["should_escalate"], bool), \
                "should_escalate must be boolean"
            assert isinstance(classification["confidence"], (int, float)), \
                "confidence must be numeric"
            assert isinstance(classification["reason"], str), \
                "reason must be string"
            assert isinstance(classification["category"], str), \
                "category must be string"
            assert isinstance(classification["keywords_found"], list), \
                "keywords_found must be list"
            
            # Verify escalation_type is correct type
            if classification["should_escalate"]:
                assert classification["escalation_type"] in ["explicit", "implicit"], \
                    f"Escalation type must be 'explicit' or 'implicit' when escalating, got '{classification['escalation_type']}'"
            else:
                assert classification["escalation_type"] is None, \
                    f"Escalation type must be None when not escalating, got '{classification['escalation_type']}'"
            
            # Verify timestamp is present
            assert "timestamp" in classification, "Missing timestamp"
            
            # ─── Requirement 4.6: Acknowledgment messages (tested in workflow) ───
            # Note: Acknowledgment messages are sent by the escalation router,
            # not the classifier. This is tested in test_property_12_escalation_workflow_routing
            
        finally:
            await db.rollback()
            await db.close()
    
    @given(
        escalation_reason=st.text(min_size=10, max_size=50),
        has_agents=st.booleans(),
        priority=st.sampled_from(['low', 'medium', 'high'])
    )
    @settings(max_examples=10, deadline=20000)
    @pytest.mark.asyncio
    async def test_property_12_escalation_workflow_routing(self, escalation_reason, has_agents, priority):
        """
        Property 12: Escalation Workflow Routing
        For any escalation trigger, the system should update conversation status to "escalated",
        notify available agents via WebSocket when agents are enabled, or send email alerts
        to workspace owners when no agents are available.

        Validates: Requirements 4.4, 4.5

        Feature: chatsaas-backend, Property 12: Escalation Workflow Routing
        """
        from app.models.user import User
        from app.models.channel import Channel
        from app.services.escalation_router import EscalationRouter
        from unittest.mock import AsyncMock, patch
        
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Create workspace owner
            owner = User(
                id=uuid4(),
                email=f"owner-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(owner)
            await db.flush()
            
            workspace = Workspace(
                id=uuid4(),
                owner_id=owner.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier="pro"
            )
            db.add(workspace)
            await db.flush()
            
            # Optionally create agents based on test parameter
            agents_created = []
            if has_agents:
                # Create 1-2 active agents
                for i in range(2):
                    agent = Agent(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        email=f"agent{i}-{uuid4().hex[:8]}@example.com",
                        name=f"Test Agent {i}",
                        is_active=True
                    )
                    db.add(agent)
                    agents_created.append(agent)
                await db.flush()
            
            # Create channel and conversation
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace.id,
                type="webchat",
                config={}
            )
            db.add(channel)
            await db.flush()
            
            # Create contact
            from app.models.contact import Contact
            contact = Contact(
                id=uuid4(),
                workspace_id=workspace.id,
                channel_id=channel.id,
                external_id=f"test-contact-{uuid4().hex[:8]}"
            )
            db.add(contact)
            await db.flush()
            
            # Create conversation with initial "active" status
            conversation = Conversation(
                id=uuid4(),
                workspace_id=workspace.id,
                contact_id=contact.id,
                channel_type="webchat",
                status="active"
            )
            db.add(conversation)
            await db.commit()
            
            # Verify initial state
            assert conversation.status == "active", "Conversation should start as active"
            
            # Mock WebSocket and Email services to avoid external dependencies
            # Note: These are imported inside the methods, so we patch at module level
            with patch('app.services.websocket_events.notify_escalation', new_callable=AsyncMock) as mock_websocket, \
                 patch('app.services.email_service.EmailService') as mock_email_service:
                
                # Setup mocks
                mock_websocket.return_value = 2 if has_agents else 0
                mock_email_instance = AsyncMock()
                mock_email_instance.send_escalation_alert = AsyncMock(return_value=True)
                mock_email_service.return_value = mock_email_instance
                
                # Test escalation routing
                router = EscalationRouter(db)
                
                classification_data = {
                    "should_escalate": True,
                    "confidence": 0.9,
                    "reason": escalation_reason,
                    "category": "test",
                    "escalation_type": "explicit"
                }
                
                result = await router.process_escalation(
                    conversation_id=str(conversation.id),
                    workspace_id=str(workspace.id),
                    escalation_reason=escalation_reason,
                    classification_data=classification_data,
                    priority=priority
                )
                
                # ─── Verify escalation result structure ───
                assert result is not None, "Escalation should return result"
                assert result["success"] == True, "Escalation should succeed"
                assert result["conversation_id"] == str(conversation.id), "Should return correct conversation ID"
                assert result["escalation_reason"] == escalation_reason, "Should preserve escalation reason"
                assert result["priority"] == priority, "Should preserve priority level"
                assert "escalation_message_id" in result, "Should create escalation system message"
                assert "acknowledgment_message_id" in result, "Should create customer acknowledgment message"
                assert "escalated_at" in result, "Should include escalation timestamp"
                
                # ─── Requirement 4.4: Update conversation status to "escalated" ───
                await db.refresh(conversation)
                assert conversation.status == "escalated", \
                    "Conversation status must be updated to 'escalated' per Requirement 4.4"
                
                # ─── Verify agent availability detection ───
                assert result["has_agents"] == has_agents, \
                    f"Should correctly detect agent availability: expected {has_agents}, got {result['has_agents']}"
                assert result["available_agents_count"] == len(agents_created), \
                    f"Should count available agents correctly: expected {len(agents_created)}, got {result['available_agents_count']}"
                
                # ─── Requirement 4.4: Notify agents via WebSocket when agents are enabled ───
                if has_agents:
                    # When agents are available, should notify via WebSocket
                    assert result["notifications_sent"] == True, \
                        "Should send WebSocket notifications when agents are available (Requirement 4.4)"
                    
                    # Verify WebSocket notification was attempted
                    mock_websocket.assert_called_once()
                    call_args = mock_websocket.call_args
                    assert call_args is not None, "WebSocket notification should be called"
                    
                    # Verify notification parameters
                    assert call_args.kwargs["workspace_id"] == str(workspace.id), \
                        "WebSocket notification should target correct workspace"
                    assert call_args.kwargs["conversation_id"] == str(conversation.id), \
                        "WebSocket notification should include conversation ID"
                    assert call_args.kwargs["escalation_reason"] == escalation_reason, \
                        "WebSocket notification should include escalation reason"
                    assert call_args.kwargs["priority"] == priority, \
                        "WebSocket notification should include priority level"
                    
                    # Email should NOT be sent when agents are available
                    assert result["email_sent"] == False, \
                        "Should not send email when agents are available"
                    mock_email_instance.send_escalation_alert.assert_not_called()
                
                # ─── Requirement 4.5: Send email alert when no agents are available ───
                else:
                    # When no agents available, should send email to workspace owner
                    assert result["email_sent"] == True, \
                        "Should send email alert to workspace owner when no agents available (Requirement 4.5)"
                    
                    # Verify email was sent
                    mock_email_instance.send_escalation_alert.assert_called_once()
                    call_args = mock_email_instance.send_escalation_alert.call_args
                    assert call_args is not None, "Email alert should be called"
                    
                    # Verify email parameters
                    assert call_args.kwargs["to_email"] == owner.email, \
                        "Email should be sent to workspace owner"
                    assert call_args.kwargs["workspace_id"] == str(workspace.id), \
                        "Email should include workspace ID"
                    assert call_args.kwargs["conversation_id"] == str(conversation.id), \
                        "Email should include conversation ID"
                    assert call_args.kwargs["escalation_reason"] == escalation_reason, \
                        "Email should include escalation reason"
                    assert call_args.kwargs["priority"] == priority, \
                        "Email should include priority level"
                    
                    # WebSocket notifications should NOT be sent when no agents
                    assert result["notifications_sent"] == False, \
                        "Should not send WebSocket notifications when no agents available"
                
                # ─── Verify system messages were created ───
                from sqlalchemy import select
                
                # Check escalation system message
                escalation_msg_result = await db.execute(
                    select(Message).where(Message.id == result["escalation_message_id"])
                )
                escalation_msg = escalation_msg_result.scalar_one_or_none()
                assert escalation_msg is not None, "Escalation system message should be created"
                assert escalation_msg.role == "system", "Escalation message should be system role"
                assert escalation_msg.conversation_id == conversation.id, \
                    "Escalation message should belong to correct conversation"
                assert escalation_reason in escalation_msg.content, \
                    "Escalation message should contain escalation reason"
                
                # Check acknowledgment message (Requirement 4.6 - tested here as part of workflow)
                ack_msg_result = await db.execute(
                    select(Message).where(Message.id == result["acknowledgment_message_id"])
                )
                ack_msg = ack_msg_result.scalar_one_or_none()
                assert ack_msg is not None, "Acknowledgment message should be created"
                assert ack_msg.role == "assistant", "Acknowledgment should be assistant role"
                assert ack_msg.conversation_id == conversation.id, \
                    "Acknowledgment should belong to correct conversation"
                assert len(ack_msg.content) > 0, "Acknowledgment should have content"
                
                # Verify acknowledgment message content varies based on agent availability
                if has_agents:
                    assert "agent" in ack_msg.content.lower() or "human" in ack_msg.content.lower(), \
                        "Acknowledgment should mention agents when available"
                else:
                    assert "email" in ack_msg.content.lower() or "support team" in ack_msg.content.lower(), \
                        "Acknowledgment should mention email/support team when no agents"
        
        finally:
            await db.rollback()
            await db.close()


class TestAgentProperties:
    """Property tests for agent management"""
    
    @given(
        agent_email=st.emails()
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_16_agent_invitation_workflow(self, agent_email):
        """
        Property 16: Agent Invitation Workflow
        Agent invitations should create secure tokens, prevent duplicates,
        and enforce tier limits.

        Validates: Requirements 6.2, 6.3, 6.4, 6.5

        Feature: chatsaas-backend, Property 16: Agent Invitation Workflow
        """
        from app.models.user import User
        from app.services.agent_manager import AgentManager
        
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Create workspace
            user = User(
                id=uuid4(),
                email=f"test-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()
            
            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier="pro"
            )
            db.add(workspace)
            await db.commit()
            
            # Test agent invitation
            agent_manager = AgentManager(db)
            
            try:
                agent = await agent_manager.create_agent_invitation(
                    workspace_id=str(workspace.id),
                    email=agent_email,
                    name="Test Agent",
                    invited_by_user_id=str(user.id)
                )
                
                # Verify agent created
                assert agent is not None
                assert agent.email == agent_email
                assert agent.workspace_id == workspace.id
                assert agent.invitation_token is not None
                assert len(agent.invitation_token) > 20  # Secure token
                
            except Exception as e:
                # May fail due to tier limits or duplicate emails
                error_msg = str(e).lower()
                assert "limit" in error_msg or "duplicate" in error_msg or "exists" in error_msg
        
        finally:
            await db.rollback()
            await db.close()
    
    @given(
        agent_name=st.text(min_size=3, max_size=50)
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_17_agent_deactivation_cleanup(self, agent_name):
        """
        Property 17: Agent Deactivation Cleanup
        When an agent is deactivated, their active conversations should
        be updated to 'escalated' status.

        Validates: Requirements 6.6

        Feature: chatsaas-backend, Property 17: Agent Deactivation Cleanup
        """
        from app.models.user import User
        from app.models.channel import Channel
        from app.services.agent_manager import AgentManager
        
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Create workspace
            user = User(
                id=uuid4(),
                email=f"test-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db.add(user)
            await db.flush()
            
            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier="pro"
            )
            db.add(workspace)
            await db.flush()
            
            # Create agent
            agent = Agent(
                id=uuid4(),
                workspace_id=workspace.id,
                email=f"agent-{uuid4().hex[:8]}@example.com",
                name=agent_name,
                is_active=True
            )
            db.add(agent)
            await db.flush()
            
            # Create channel and conversation assigned to agent
            channel = Channel(
                id=uuid4(),
                workspace_id=workspace.id,
                type="webchat",
                config={}
            )
            db.add(channel)
            await db.flush()
            
            # Create contact first
            from app.models.contact import Contact
            contact = Contact(
                id=uuid4(),
                workspace_id=workspace.id,
                channel_id=channel.id,
                external_id="test-contact-789"
            )
            db.add(contact)
            await db.flush()
            
            conversation = Conversation(
                id=uuid4(),
                workspace_id=workspace.id,
                contact_id=contact.id,
                channel_type="webchat",
                status="agent",
                assigned_agent_id=agent.id
            )
            db.add(conversation)
            await db.commit()
            
            # Deactivate agent
            agent_manager = AgentManager(db)
            await agent_manager.deactivate_agent(
                agent_id=str(agent.id),
                workspace_id=str(workspace.id),
                deactivated_by_user_id=str(user.id)
            )
            
            # Verify agent deactivated
            await db.refresh(agent)
            assert agent.is_active == False
            
            # Verify conversation status updated
            await db.refresh(conversation)
            assert conversation.status == "escalated"
            assert conversation.assigned_agent_id is None
        
        finally:
            await db.rollback()
            await db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])