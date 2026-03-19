"""
Property-Based Test for Usage Counter Management
Tests Property 22 from the design document.
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from hypothesis.strategies import composite
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app.database import get_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.usage_counter import UsageCounter
from app.services.usage_tracker import UsageTracker
from app.services.tier_manager import TierManager, TierLimitError
from app.config import TIER_LIMITS


@composite
def tier_name(draw):
    """Generate valid tier names"""
    return draw(st.sampled_from(['free', 'starter', 'growth', 'pro']))


@composite
def month_string(draw):
    """Generate valid month strings in YYYY-MM format"""
    year = draw(st.integers(min_value=2024, max_value=2026))
    month = draw(st.integers(min_value=1, max_value=12))
    return f"{year}-{month:02d}"


@composite
def message_count(draw):
    """Generate message counts for testing"""
    return draw(st.integers(min_value=0, max_value=1000))


@composite
def token_count(draw):
    """Generate token counts for testing"""
    return draw(st.integers(min_value=0, max_value=10000))


class TestUsageCounterManagementProperties:
    """Property tests for usage counter management"""
    
    @given(
        tier=tier_name(),
        initial_messages=message_count(),
        additional_messages=st.integers(min_value=1, max_value=100),
        input_tokens=token_count(),
        output_tokens=token_count()
    )
    @settings(max_examples=5, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_22_accurate_usage_tracking(
        self, 
        tier,
        initial_messages,
        additional_messages,
        input_tokens,
        output_tokens
    ):
        """
        Property 22: Usage Counter Management (Part 1 - Accurate Tracking)
        
        For any workspace usage tracking, the system should accurately track
        message counts and token usage, incrementing counters correctly with
        each operation and maintaining accurate totals.
        
        Validates: Requirements 9.6
        
        **Validates: Requirements 9.6**
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
            await db.flush()
            
            # Create initial usage counter
            current_month = UsageTracker.get_current_month()
            usage_counter = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=current_month,
                messages_sent=initial_messages,
                tokens_used=0
            )
            db.add(usage_counter)
            await db.commit()
            
            # Create usage tracker
            tracker = UsageTracker(db)
            
            # Test 1: Verify initial state is tracked correctly
            usage = await tracker.get_monthly_usage(str(workspace.id))
            assert usage['message_count'] == initial_messages, \
                f"Initial message count should be {initial_messages}, got {usage['message_count']}"
            assert usage['tokens_used'] == 0, \
                f"Initial token count should be 0, got {usage['tokens_used']}"
            
            # Test 2: Increment usage and verify accurate tracking
            await tracker.increment_message_count(
                workspace_id=str(workspace.id),
                count=additional_messages,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )
            
            # Calculate expected values
            expected_messages = initial_messages + additional_messages
            expected_tokens = input_tokens + output_tokens
            
            # Test 3: Verify persistence - fetch from database to get latest state
            # The increment_message_count commits internally, so we need to query fresh
            usage_after = await tracker.get_monthly_usage(str(workspace.id))
            assert usage_after['message_count'] == expected_messages, \
                f"Message count should be {expected_messages}, got {usage_after['message_count']}"
            assert usage_after['tokens_used'] == expected_tokens, \
                f"Token count should be {expected_tokens}, got {usage_after['tokens_used']}"
            
            # Test 4: Verify multiple increments accumulate correctly
            await tracker.increment_message_count(
                workspace_id=str(workspace.id),
                count=1,
                input_tokens=50,
                output_tokens=30
            )
            
            expected_messages_2 = expected_messages + 1
            expected_tokens_2 = expected_tokens + 50 + 30
            
            # Query fresh to get updated values
            usage_after_second = await tracker.get_monthly_usage(str(workspace.id))
            assert usage_after_second['message_count'] == expected_messages_2, \
                "Multiple increments should accumulate correctly"
            assert usage_after_second['tokens_used'] == expected_tokens_2, \
                "Token usage should accumulate correctly across increments"
            
            # Test 5: Verify usage tracking prevents limit violations
            tier_manager = TierManager(db)
            
            # Get fresh tier info after increments
            tier_info = await tier_manager.get_workspace_tier_info(str(workspace.id))
            
            # Check if we're within or over limits
            monthly_limit = TIER_LIMITS[tier]['monthly_messages']
            current_usage = tier_info['usage']['monthly_messages']
            
            assert current_usage == expected_messages_2, \
                f"Tier manager should see accurate usage from tracker: expected {expected_messages_2}, got {current_usage}"
            
            # If we're over the limit, verify that limit checking works
            if current_usage >= monthly_limit:
                with pytest.raises(TierLimitError):
                    await tier_manager.check_monthly_message_limit(
                        str(workspace.id),
                        additional_messages=1
                    )
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name(),
        month1=month_string(),
        month2=month_string(),
        messages_month1=message_count(),
        messages_month2=message_count()
    )
    @settings(max_examples=5, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_22_monthly_reset_functionality(
        self, 
        tier,
        month1,
        month2,
        messages_month1,
        messages_month2
    ):
        """
        Property 22: Usage Counter Management (Part 2 - Monthly Reset)
        
        For any workspace usage tracking, the system should maintain separate
        counters for each month, automatically creating new counters for new
        months and resetting limits on the first day of each month.
        
        Validates: Requirements 9.6
        
        **Validates: Requirements 9.6**
        """
        # Ensure months are different
        assume(month1 != month2)
        
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
            await db.flush()
            
            # Create usage counter for month1
            counter_month1 = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=month1,
                messages_sent=messages_month1,
                tokens_used=1000
            )
            db.add(counter_month1)
            
            # Create usage counter for month2
            counter_month2 = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=month2,
                messages_sent=messages_month2,
                tokens_used=2000
            )
            db.add(counter_month2)
            await db.commit()
            
            # Create usage tracker
            tracker = UsageTracker(db)
            
            # Test 1: Verify separate counters for different months
            usage_month1 = await tracker.get_monthly_usage(str(workspace.id), month1)
            usage_month2 = await tracker.get_monthly_usage(str(workspace.id), month2)
            
            assert usage_month1['month'] == month1
            assert usage_month1['message_count'] == messages_month1
            assert usage_month1['tokens_used'] == 1000
            
            assert usage_month2['month'] == month2
            assert usage_month2['message_count'] == messages_month2
            assert usage_month2['tokens_used'] == 2000
            
            # Test 2: Verify counters are independent
            # Incrementing one month should not affect the other
            await tracker.increment_message_count(
                workspace_id=str(workspace.id),
                count=10,
                input_tokens=50,
                output_tokens=30
            )
            
            # Get current month (should be one of the test months or a new one)
            current_month = UsageTracker.get_current_month()
            
            # Verify the non-current months remain unchanged
            if current_month != month1:
                usage_month1_after = await tracker.get_monthly_usage(str(workspace.id), month1)
                assert usage_month1_after['message_count'] == messages_month1, \
                    "Past month counters should not be affected by current month increments"
            
            if current_month != month2:
                usage_month2_after = await tracker.get_monthly_usage(str(workspace.id), month2)
                assert usage_month2_after['message_count'] == messages_month2, \
                    "Past month counters should not be affected by current month increments"
            
            # Test 3: Verify usage history retrieves multiple months
            history = await tracker.get_usage_history(str(workspace.id), months=6)
            
            # Should have at least the two months we created
            assert len(history) >= 2, "Usage history should include multiple months"
            
            # Verify history is ordered by month (newest first)
            months_in_history = [h['month'] for h in history]
            assert months_in_history == sorted(months_in_history, reverse=True), \
                "Usage history should be ordered by month (newest first)"
            
            # Test 4: Verify monthly reset behavior
            # Reset month1 counter
            reset_success = await tracker.reset_monthly_counter(str(workspace.id), month1)
            assert reset_success == True, "Reset should succeed for existing counter"
            
            # Verify counter was reset
            usage_month1_reset = await tracker.get_monthly_usage(str(workspace.id), month1)
            assert usage_month1_reset['message_count'] == 0, \
                "Message count should be 0 after reset"
            assert usage_month1_reset['tokens_used'] == 0, \
                "Token count should be 0 after reset"
            
            # Verify other month was not affected
            usage_month2_after_reset = await tracker.get_monthly_usage(str(workspace.id), month2)
            assert usage_month2_after_reset['message_count'] == messages_month2, \
                "Other month counters should not be affected by reset"
            
            # Test 5: Verify automatic counter creation for new months
            new_month = "2027-12"  # Future month unlikely to exist
            
            # Getting usage for non-existent month should create it
            usage_new_month = await tracker.get_monthly_usage(str(workspace.id), new_month)
            assert usage_new_month['month'] == new_month
            assert usage_new_month['message_count'] == 0, \
                "New month counter should start at 0"
            assert usage_new_month['tokens_used'] == 0, \
                "New month token counter should start at 0"
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name(),
        usage_percentage=st.floats(min_value=0.0, max_value=1.5)
    )
    @settings(max_examples=5, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_22_limit_enforcement_integration(
        self, 
        tier,
        usage_percentage
    ):
        """
        Property 22: Usage Counter Management (Part 3 - Limit Enforcement)
        
        For any workspace usage tracking, the system should prevent resource
        creation when limits are exceeded, accurately checking current usage
        against tier limits and rejecting operations that would exceed limits.
        
        Validates: Requirements 9.6
        
        **Validates: Requirements 9.6**
        """
        # Get database session
        db_gen = get_db()
        db = await anext(db_gen)
        
        try:
            # Get tier limits
            tier_limits = TIER_LIMITS[tier]
            monthly_limit = tier_limits['monthly_messages']
            
            # Calculate usage based on percentage of limit
            current_usage = int(monthly_limit * usage_percentage)
            
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
            
            # Create usage counter with current usage
            current_month = UsageTracker.get_current_month()
            usage_counter = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=current_month,
                messages_sent=current_usage,
                tokens_used=0
            )
            db.add(usage_counter)
            await db.commit()
            
            # Create tier manager and usage tracker
            tier_manager = TierManager(db)
            tracker = UsageTracker(db)
            
            # Test 1: Verify usage is tracked correctly
            tier_info = await tier_manager.get_workspace_tier_info(str(workspace.id))
            assert tier_info['usage']['monthly_messages'] == current_usage, \
                "Tier manager should see accurate usage from counter"
            
            # Test 2: Verify limit enforcement based on current usage
            is_within_limit = current_usage < monthly_limit
            is_at_or_over_limit = current_usage >= monthly_limit
            
            if is_within_limit:
                # Should allow additional messages when within limit
                try:
                    result = await tier_manager.check_monthly_message_limit(
                        str(workspace.id),
                        additional_messages=1
                    )
                    assert result == True, "Should allow messages when within limit"
                except TierLimitError:
                    pytest.fail("Should not raise error when within limits")
                
                # Verify we can increment usage
                await tracker.increment_message_count(
                    workspace_id=str(workspace.id),
                    count=1,
                    input_tokens=10,
                    output_tokens=5
                )
                
                # Query fresh to verify increment
                usage_after_increment = await tracker.get_monthly_usage(str(workspace.id))
                assert usage_after_increment['message_count'] == current_usage + 1, \
                    f"Should be able to increment usage when within limits: expected {current_usage + 1}, got {usage_after_increment['message_count']}"
            
            elif is_at_or_over_limit:
                # Should reject additional messages when at or over limit
                with pytest.raises(TierLimitError) as exc_info:
                    await tier_manager.check_monthly_message_limit(
                        str(workspace.id),
                        additional_messages=1
                    )
                
                # Verify error message is descriptive
                error_message = str(exc_info.value)
                assert "monthly message limit" in error_message.lower(), \
                    "Error should mention monthly message limit"
                assert tier in error_message.lower(), \
                    f"Error should mention tier '{tier}'"
            
            # Test 3: Verify remaining capacity calculation
            remaining = tier_info['remaining']['monthly_messages']
            expected_remaining = max(0, monthly_limit - current_usage)
            
            assert remaining == expected_remaining, \
                f"Remaining capacity should be {expected_remaining}, got {remaining}"
            assert remaining >= 0, \
                "Remaining capacity should never be negative"
            
            # Test 4: Verify batch message limit checking
            # Try to add messages that would exceed limit
            if is_within_limit:
                # Calculate how many messages would exceed limit
                messages_to_exceed = (monthly_limit - current_usage) + 10
                
                with pytest.raises(TierLimitError):
                    await tier_manager.check_monthly_message_limit(
                        str(workspace.id),
                        additional_messages=messages_to_exceed
                    )
            
            # Test 5: Verify total usage tracking
            total_usage = await tracker.get_workspace_total_usage(str(workspace.id))
            assert total_usage['total_messages'] == current_usage, \
                "Total usage should match current month usage"
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name(),
        num_increments=st.integers(min_value=1, max_value=20)
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_22_concurrent_usage_tracking(
        self, 
        tier,
        num_increments
    ):
        """
        Property 22: Usage Counter Management (Part 4 - Concurrent Updates)
        
        For any workspace usage tracking, the system should handle concurrent
        usage increments correctly, maintaining accurate counts even when
        multiple operations update the counter simultaneously.
        
        Validates: Requirements 9.6
        
        **Validates: Requirements 9.6**
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
            await db.flush()
            
            # Create initial usage counter
            current_month = UsageTracker.get_current_month()
            usage_counter = UsageCounter(
                id=uuid4(),
                workspace_id=workspace.id,
                month=current_month,
                messages_sent=0,
                tokens_used=0
            )
            db.add(usage_counter)
            await db.commit()
            
            # Create usage tracker
            tracker = UsageTracker(db)
            
            # Test 1: Perform multiple sequential increments
            for i in range(num_increments):
                await tracker.increment_message_count(
                    workspace_id=str(workspace.id),
                    count=1,
                    input_tokens=10,
                    output_tokens=5
                )
            
            # Test 2: Verify all increments were tracked correctly
            final_usage = await tracker.get_monthly_usage(str(workspace.id))
            
            expected_messages = num_increments
            expected_tokens = num_increments * (10 + 5)
            
            assert final_usage['message_count'] == expected_messages, \
                f"After {num_increments} increments, should have {expected_messages} messages, got {final_usage['message_count']}"
            assert final_usage['tokens_used'] == expected_tokens, \
                f"After {num_increments} increments, should have {expected_tokens} tokens, got {final_usage['tokens_used']}"
            
            # Test 3: Verify counter persistence across multiple reads
            for _ in range(3):
                usage = await tracker.get_monthly_usage(str(workspace.id))
                assert usage['message_count'] == expected_messages, \
                    "Usage should remain consistent across multiple reads"
                assert usage['tokens_used'] == expected_tokens, \
                    "Token usage should remain consistent across multiple reads"
            
            # Test 4: Verify get_or_create_counter idempotency
            # Multiple calls should return the same counter
            counter1 = await tracker.get_or_create_counter(str(workspace.id))
            counter2 = await tracker.get_or_create_counter(str(workspace.id))
            
            assert counter1.id == counter2.id, \
                "get_or_create_counter should return same counter"
            assert counter1.messages_sent == counter2.messages_sent, \
                "Counter values should be consistent"
        
        finally:
            # Cleanup
            await db.rollback()
            await db.close()
    
    @given(
        tier=tier_name()
    )
    @settings(max_examples=3, deadline=15000)
    @pytest.mark.asyncio
    async def test_property_22_usage_counter_persistence(
        self, 
        tier
    ):
        """
        Property 22: Usage Counter Management (Part 5 - Persistence)
        
        For any workspace usage tracking, usage counters should persist
        correctly across database sessions, maintaining accurate state
        even after commits and session closures.
        
        Validates: Requirements 9.6
        
        **Validates: Requirements 9.6**
        """
        workspace_id = None
        
        # Session 1: Create workspace and usage counter
        db_gen1 = get_db()
        db1 = await anext(db_gen1)
        
        try:
            # Create user and workspace
            user = User(
                id=uuid4(),
                email=f"test-{uuid4().hex[:8]}@example.com",
                hashed_password="$2b$12$test_hash",
                is_active=True
            )
            db1.add(user)
            await db1.flush()
            
            workspace = Workspace(
                id=uuid4(),
                owner_id=user.id,
                name="Test Business",
                slug=f"test-{uuid4().hex[:8]}",
                tier=tier
            )
            db1.add(workspace)
            await db1.flush()
            
            workspace_id = str(workspace.id)
            
            # Create usage tracker and increment usage
            tracker1 = UsageTracker(db1)
            await tracker1.increment_message_count(
                workspace_id=workspace_id,
                count=50,
                input_tokens=500,
                output_tokens=300
            )
            
            # Verify usage in first session
            usage1 = await tracker1.get_monthly_usage(workspace_id)
            assert usage1['message_count'] == 50
            assert usage1['tokens_used'] == 800
            
            await db1.commit()
        
        finally:
            await db1.close()
        
        # Session 2: Verify persistence in new session
        db_gen2 = get_db()
        db2 = await anext(db_gen2)
        
        try:
            # Create new tracker with new session
            tracker2 = UsageTracker(db2)
            
            # Verify usage persisted from previous session
            usage2 = await tracker2.get_monthly_usage(workspace_id)
            assert usage2['message_count'] == 50, \
                "Usage should persist across database sessions"
            assert usage2['tokens_used'] == 800, \
                "Token usage should persist across database sessions"
            
            # Increment usage in second session
            await tracker2.increment_message_count(
                workspace_id=workspace_id,
                count=25,
                input_tokens=250,
                output_tokens=150
            )
            
            # Verify cumulative usage
            usage2_after = await tracker2.get_monthly_usage(workspace_id)
            assert usage2_after['message_count'] == 75, \
                "Usage should accumulate across sessions"
            assert usage2_after['tokens_used'] == 1200, \
                "Token usage should accumulate across sessions"
            
            await db2.commit()
        
        finally:
            await db2.close()
        
        # Session 3: Final verification
        db_gen3 = get_db()
        db3 = await anext(db_gen3)
        
        try:
            tracker3 = UsageTracker(db3)
            
            # Verify final state
            usage3 = await tracker3.get_monthly_usage(workspace_id)
            assert usage3['message_count'] == 75, \
                "Final usage should reflect all increments"
            assert usage3['tokens_used'] == 1200, \
                "Final token usage should reflect all increments"
            
            # Verify total usage
            total_usage = await tracker3.get_workspace_total_usage(workspace_id)
            assert total_usage['total_messages'] == 75
            assert total_usage['total_tokens'] == 1200
        
        finally:
            await db3.rollback()
            await db3.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
