"""
Property-Based Test for Tier Limit Enforcement
Tests Property 6 from the design document.
"""

import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.database import get_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.channel import Channel
from app.models.agent import Agent
from app.models.document import Document
from app.models.usage_counter import UsageCounter
from app.services.tier_manager import TierManager, TierLimitError
from app.config import TIER_LIMITS


@composite
def tier_name(draw):
    """Generate valid tier names"""
    return draw(st.sampled_from(['free', 'starter', 'growth', 'pro']))


@composite
def resource_type(draw):
    """Generate valid resource types"""
    return draw(st.sampled_from(['channels', 'agents', 'documents', 'messages']))


@composite
def resource_count(draw):
    """Generate resource counts for testing"""
    return draw(st.integers(min_value=0, max_value=10))


class TestTierLimitEnforcementProperties:
    """Property tests for tier limit enforcement"""
    
    @given(
        tier=tier_name(),
        resource_type=resource_type(),
        current_count=resource_count()
    )
    @settings(max_examples=5, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_6_tier_limit_enforcement(
        self, 
        tier, 
        resource_type,
        current_count
    ):
        """
        Property 6: Tier Limit Enforcement
        
        For any workspace tier and resource type (channels, agents, documents, messages),
        attempting to exceed the tier-specific limits should be rejected with descriptive
        error messages while staying within limits should succeed.
        
        Validates: Requirements 2.6, 6.1, 9.1, 9.2, 9.3, 9.4, 9.5
        
        **Validates: Requirements 2.6, 6.1, 9.1, 9.2, 9.3, 9.4, 9.5**
        """
        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Get tier limits for this tier
            tier_limits = TIER_LIMITS[tier]
            
            # Determine the limit for this resource type
            if resource_type == 'channels':
                limit = tier_limits['channels']
            elif resource_type == 'agents':
                limit = tier_limits['agents']
            elif resource_type == 'documents':
                limit = tier_limits['documents_max']
            elif resource_type == 'messages':
                limit = tier_limits['monthly_messages']
            
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
            await db.flush()
            
            # Create existing resources up to current_count
            # Cap current_count at limit + 5 to avoid creating too many resources
            actual_current_count = min(current_count, limit + 5)
            
            if resource_type == 'channels':
                # Channel types available (note: there's a unique constraint on workspace_id + type)
                channel_types = ['webchat', 'telegram', 'whatsapp', 'instagram']
                # Can't create more channels than available types due to unique constraint
                actual_current_count = min(actual_current_count, len(channel_types))
                for i in range(actual_current_count):
                    # Use different channel types to avoid unique constraint violation
                    channel_type = channel_types[i]
                    channel = Channel(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        type=channel_type,
                        config={}
                    )
                    db.add(channel)
            
            elif resource_type == 'agents':
                for i in range(actual_current_count):
                    agent = Agent(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        email=f"agent-{uuid4().hex[:8]}@example.com",
                        name=f"Agent {i}",
                        is_active=True
                    )
                    db.add(agent)
            
            elif resource_type == 'documents':
                for i in range(actual_current_count):
                    document = Document(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        name=f"doc-{uuid4().hex[:8]}.txt",
                        file_path=f"/tmp/doc-{i}.txt",
                        status="ready"
                    )
                    db.add(document)
            
            elif resource_type == 'messages':
                # For messages, create usage counter with current count
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                usage_counter = UsageCounter(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    month=current_month,
                    messages_sent=actual_current_count,
                    tokens_used=0
                )
                db.add(usage_counter)
            
            await db.commit()
            
            # Create tier manager
            tier_manager = TierManager(db)
            
            # Test 1: Verify current usage is tracked correctly
            tier_info = await tier_manager.get_workspace_tier_info(str(workspace.id))
            
            assert tier_info['tier'] == tier
            assert tier_info['limits'] == tier_limits
            
            if resource_type == 'channels':
                assert tier_info['usage']['channels'] == actual_current_count
            elif resource_type == 'agents':
                assert tier_info['usage']['agents'] == actual_current_count
            elif resource_type == 'documents':
                assert tier_info['usage']['documents'] == actual_current_count
            elif resource_type == 'messages':
                assert tier_info['usage']['monthly_messages'] == actual_current_count
            
            # Test 2: Check if we're within limits or at/over limits
            is_within_limit = actual_current_count < limit
            is_at_or_over_limit = actual_current_count >= limit
            
            # Test 3: Attempt to add one more resource
            if is_within_limit:
                # Should succeed when within limits
                try:
                    if resource_type == 'channels':
                        result = await tier_manager.check_channel_limit(str(workspace.id))
                        assert result == True, "Should allow channel creation when within limit"
                    
                    elif resource_type == 'agents':
                        result = await tier_manager.check_agent_limit(str(workspace.id))
                        assert result == True, "Should allow agent creation when within limit"
                    
                    elif resource_type == 'documents':
                        result = await tier_manager.check_document_limit(str(workspace.id))
                        assert result == True, "Should allow document upload when within limit"
                    
                    elif resource_type == 'messages':
                        result = await tier_manager.check_monthly_message_limit(
                            str(workspace.id), 
                            additional_messages=1
                        )
                        assert result == True, "Should allow message processing when within limit"
                
                except TierLimitError as e:
                    # Should not raise error when within limits
                    pytest.fail(f"Unexpected TierLimitError when within limits: {e}")
            
            elif is_at_or_over_limit:
                # Should fail when at or over limits
                with pytest.raises(TierLimitError) as exc_info:
                    if resource_type == 'channels':
                        await tier_manager.check_channel_limit(str(workspace.id))
                    
                    elif resource_type == 'agents':
                        await tier_manager.check_agent_limit(str(workspace.id))
                    
                    elif resource_type == 'documents':
                        await tier_manager.check_document_limit(str(workspace.id))
                    
                    elif resource_type == 'messages':
                        await tier_manager.check_monthly_message_limit(
                            str(workspace.id), 
                            additional_messages=1
                        )
                
                # Test 4: Verify error message is descriptive
                error_message = str(exc_info.value)
                
                # Error should mention the tier
                assert tier in error_message.lower(), \
                    f"Error message should mention tier '{tier}': {error_message}"
                
                # Error should mention the limit
                assert str(limit) in error_message or "limit" in error_message.lower(), \
                    f"Error message should mention limit: {error_message}"
                
                # Error should mention the resource type
                if resource_type == 'channels':
                    assert "channel" in error_message.lower(), \
                        f"Error message should mention channels: {error_message}"
                elif resource_type == 'agents':
                    assert "agent" in error_message.lower(), \
                        f"Error message should mention agents: {error_message}"
                elif resource_type == 'documents':
                    assert "document" in error_message.lower(), \
                        f"Error message should mention documents: {error_message}"
                elif resource_type == 'messages':
                    assert "message" in error_message.lower(), \
                        f"Error message should mention messages: {error_message}"
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name(),
        additional_messages=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_6_message_limit_batch_enforcement(
        self, 
        tier,
        additional_messages
    ):
        """
        Property 6: Tier Limit Enforcement (Message Batch Variant)
        
        For any workspace tier, attempting to process multiple messages at once
        should correctly enforce monthly message limits, rejecting batches that
        would exceed the limit even if current usage is below the limit.
        
        Validates: Requirements 9.4, 9.5
        
        **Validates: Requirements 9.4, 9.5**
        """
        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Get tier limits
            tier_limits = TIER_LIMITS[tier]
            monthly_message_limit = tier_limits['monthly_messages']
            
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
                tier=tier
            )
            db.add(workspace)
            await db.flush()
            
            # Set current usage to be close to limit
            # Use a value that's 80-95% of the limit
            current_usage = int(monthly_message_limit * 0.9)
            
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            usage_counter = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=current_month,
                messages_sent=current_usage,
                tokens_used=0
            )
            db.add(usage_counter)
            await db.commit()
            
            # Create tier manager
            tier_manager = TierManager(db)
            
            # Calculate if batch would exceed limit
            would_exceed = (current_usage + additional_messages) > monthly_message_limit
            
            # Test batch message limit enforcement
            if would_exceed:
                # Should raise TierLimitError
                with pytest.raises(TierLimitError) as exc_info:
                    await tier_manager.check_monthly_message_limit(
                        str(workspace.id),
                        additional_messages=additional_messages
                    )
                
                # Verify error message
                error_message = str(exc_info.value)
                assert "monthly message limit" in error_message.lower()
                assert tier in error_message.lower()
            
            else:
                # Should succeed
                result = await tier_manager.check_monthly_message_limit(
                    str(workspace.id),
                    additional_messages=additional_messages
                )
                assert result == True
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name()
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_6_tier_specific_limits_correctness(self, tier):
        """
        Property 6: Tier Limit Enforcement (Tier Correctness Variant)
        
        For any tier, the system should enforce the exact limits specified
        in the requirements:
        - free: 1 channel, 0 agents, 3 documents, 500 messages
        - starter: 2 channels, 0 agents, 10 documents, 2000 messages
        - growth: 4 channels, 0 agents, 25 documents, 10000 messages
        - pro: 4 channels, 2 agents, 100 documents, 50000 messages
        
        Validates: Requirements 9.1, 9.2, 9.3, 9.4
        
        **Validates: Requirements 9.1, 9.2, 9.3, 9.4**
        """
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
                tier=tier
            )
            db.add(workspace)
            await db.commit()
            
            # Create tier manager
            tier_manager = TierManager(db)
            
            # Get tier info
            tier_info = await tier_manager.get_workspace_tier_info(str(workspace.id))
            
            # Verify tier limits match requirements
            expected_limits = TIER_LIMITS[tier]
            
            assert tier_info['limits']['channels'] == expected_limits['channels'], \
                f"Channel limit mismatch for {tier} tier"
            
            assert tier_info['limits']['agents'] == expected_limits['agents'], \
                f"Agent limit mismatch for {tier} tier"
            
            assert tier_info['limits']['documents_max'] == expected_limits['documents_max'], \
                f"Document limit mismatch for {tier} tier"
            
            assert tier_info['limits']['monthly_messages'] == expected_limits['monthly_messages'], \
                f"Monthly message limit mismatch for {tier} tier"
            
            # Verify specific requirements
            if tier == 'free':
                assert tier_info['limits']['channels'] == 1
                assert tier_info['limits']['agents'] == 0
                assert tier_info['limits']['documents_max'] == 3
                assert tier_info['limits']['monthly_messages'] == 500
            
            elif tier == 'starter':
                assert tier_info['limits']['channels'] == 2
                assert tier_info['limits']['agents'] == 0
                assert tier_info['limits']['documents_max'] == 10
                assert tier_info['limits']['monthly_messages'] == 2000
            
            elif tier == 'growth':
                assert tier_info['limits']['channels'] == 4
                assert tier_info['limits']['agents'] == 0
                assert tier_info['limits']['documents_max'] == 25
                assert tier_info['limits']['monthly_messages'] == 10000
            
            elif tier == 'pro':
                assert tier_info['limits']['channels'] == 4
                assert tier_info['limits']['agents'] == 2
                assert tier_info['limits']['documents_max'] == 100
                assert tier_info['limits']['monthly_messages'] == 50000
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name(),
        resource_type=resource_type()
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_6_remaining_capacity_calculation(
        self, 
        tier,
        resource_type
    ):
        """
        Property 6: Tier Limit Enforcement (Remaining Capacity Variant)
        
        For any workspace tier and resource type, the system should correctly
        calculate remaining capacity as (limit - current_usage), and this
        calculation should be accurate and non-negative.
        
        Validates: Requirements 2.6, 6.1, 9.1, 9.2, 9.3, 9.4, 9.5
        
        **Validates: Requirements 2.6, 6.1, 9.1, 9.2, 9.3, 9.4, 9.5**
        """
        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Get tier limits
            tier_limits = TIER_LIMITS[tier]
            
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
                tier=tier
            )
            db.add(workspace)
            await db.flush()
            
            # Create some resources (50% of limit)
            if resource_type == 'channels':
                limit = tier_limits['channels']
                count = max(0, limit // 2)
                channel_types = ['webchat', 'telegram', 'whatsapp', 'instagram']
                # Can't create more channels than available types due to unique constraint
                count = min(count, len(channel_types))
                for i in range(count):
                    channel_type = channel_types[i]
                    channel = Channel(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        type=channel_type,
                        config={}
                    )
                    db.add(channel)
            
            elif resource_type == 'agents':
                limit = tier_limits['agents']
                count = max(0, limit // 2)
                for i in range(count):
                    agent = Agent(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        email=f"agent-{uuid4().hex[:8]}@example.com",
                        name=f"Agent {i}",
                        is_active=True
                    )
                    db.add(agent)
            
            elif resource_type == 'documents':
                limit = tier_limits['documents_max']
                count = max(0, limit // 2)
                for i in range(count):
                    document = Document(
                        id=uuid4(),
                        workspace_id=workspace.id,
                        name=f"doc-{uuid4().hex[:8]}.txt",
                        file_path=f"/tmp/doc-{i}.txt",
                        status="ready"
                    )
                    db.add(document)
            
            elif resource_type == 'messages':
                limit = tier_limits['monthly_messages']
                count = max(0, limit // 2)
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                usage_counter = UsageCounter(
                    id=uuid4(),
                    workspace_id=workspace.id,
                    month=current_month,
                    messages_sent=count,
                    tokens_used=0
                )
                db.add(usage_counter)
            
            await db.commit()
            
            # Create tier manager and get tier info
            tier_manager = TierManager(db)
            tier_info = await tier_manager.get_workspace_tier_info(str(workspace.id))
            
            # Verify remaining capacity calculation
            if resource_type == 'channels':
                limit = tier_limits['channels']
                usage = tier_info['usage']['channels']
                remaining = tier_info['remaining']['channels']
                
                assert remaining == max(0, limit - usage), \
                    f"Remaining channels calculation incorrect: {remaining} != max(0, {limit} - {usage})"
                assert remaining >= 0, "Remaining capacity should never be negative"
            
            elif resource_type == 'agents':
                limit = tier_limits['agents']
                usage = tier_info['usage']['agents']
                remaining = tier_info['remaining']['agents']
                
                assert remaining == max(0, limit - usage), \
                    f"Remaining agents calculation incorrect: {remaining} != max(0, {limit} - {usage})"
                assert remaining >= 0, "Remaining capacity should never be negative"
            
            elif resource_type == 'documents':
                limit = tier_limits['documents_max']
                usage = tier_info['usage']['documents']
                remaining = tier_info['remaining']['documents']
                
                assert remaining == max(0, limit - usage), \
                    f"Remaining documents calculation incorrect: {remaining} != max(0, {limit} - {usage})"
                assert remaining >= 0, "Remaining capacity should never be negative"
            
            elif resource_type == 'messages':
                limit = tier_limits['monthly_messages']
                usage = tier_info['usage']['monthly_messages']
                remaining = tier_info['remaining']['monthly_messages']
                
                assert remaining == max(0, limit - usage), \
                    f"Remaining messages calculation incorrect: {remaining} != max(0, {limit} - {usage})"
                assert remaining >= 0, "Remaining capacity should never be negative"
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
