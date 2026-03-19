"""
Usage Counter Management Service
Tracks monthly usage and token consumption with automatic reset functionality
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert

from app.models.usage_counter import UsageCounter


class UsageTracker:
    """
    Manages usage counters with monthly reset functionality
    Tracks message counts and token consumption per workspace
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    @staticmethod
    def get_current_month() -> str:
        """Get current month in YYYY-MM format"""
        return datetime.now(timezone.utc).strftime("%Y-%m")
    
    async def get_or_create_counter(self, workspace_id: str, month: Optional[str] = None) -> UsageCounter:
        """
        Get or create usage counter for workspace and month
        
        Args:
            workspace_id: Workspace ID
            month: Month in YYYY-MM format (defaults to current month)
        
        Returns:
            UsageCounter instance
        """
        if month is None:
            month = self.get_current_month()
        
        # Try to get existing counter
        result = await self.db.execute(
            select(UsageCounter)
            .where(UsageCounter.workspace_id == workspace_id)
            .where(UsageCounter.month == month)
        )
        counter = result.scalar_one_or_none()
        
        if counter:
            return counter
        
        # Create new counter using PostgreSQL UPSERT
        stmt = insert(UsageCounter).values(
            workspace_id=workspace_id,
            month=month,
            messages_sent=0,
            tokens_used=0
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=['workspace_id', 'month']
        )
        
        await self.db.execute(stmt)
        await self.db.commit()
        
        # Fetch the counter (either newly created or existing from race condition)
        result = await self.db.execute(
            select(UsageCounter)
            .where(UsageCounter.workspace_id == workspace_id)
            .where(UsageCounter.month == month)
        )
        return result.scalar_one()
    
    async def increment_message_count(
        self, 
        workspace_id: str, 
        count: int = 1,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> UsageCounter:
        """
        Increment message count and token usage for current month
        
        Args:
            workspace_id: Workspace ID
            count: Number of messages to add (default: 1)
            input_tokens: Input tokens consumed
            output_tokens: Output tokens consumed
        
        Returns:
            Updated UsageCounter
        """
        month = self.get_current_month()
        
        # Ensure counter exists
        await self.get_or_create_counter(workspace_id, month)
        
        # Calculate total tokens
        total_tokens = input_tokens + output_tokens
        
        # Update counters atomically
        stmt = update(UsageCounter).where(
            UsageCounter.workspace_id == workspace_id,
            UsageCounter.month == month
        ).values(
            messages_sent=UsageCounter.messages_sent + count,
            tokens_used=UsageCounter.tokens_used + total_tokens,
            updated_at=datetime.now(timezone.utc)
        ).returning(UsageCounter)
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        # expire_on_commit=False means stale identity map entries persist after commit.
        # Expire manually so scalar_one() loads fresh values from the RETURNING buffer.
        self.db.expire_all()

        return result.scalar_one()
    
    async def get_monthly_usage(self, workspace_id: str, month: Optional[str] = None) -> Dict[str, int]:
        """
        Get usage statistics for a specific month
        
        Args:
            workspace_id: Workspace ID
            month: Month in YYYY-MM format (defaults to current month)
        
        Returns:
            Dict with usage statistics
        """
        if month is None:
            month = self.get_current_month()
        
        counter = await self.get_or_create_counter(workspace_id, month)
        
        return {
            "month": month,
            "message_count": counter.messages_sent,
            "tokens_used": counter.tokens_used
        }
    
    async def get_usage_history(self, workspace_id: str, months: int = 6) -> list[Dict[str, Any]]:
        """
        Get usage history for the last N months
        
        Args:
            workspace_id: Workspace ID
            months: Number of months to retrieve (default: 6)
        
        Returns:
            List of usage statistics ordered by month (newest first)
        """
        result = await self.db.execute(
            select(UsageCounter)
            .where(UsageCounter.workspace_id == workspace_id)
            .order_by(UsageCounter.month.desc())
            .limit(months)
        )
        counters = result.scalars().all()
        
        return [
            {
                "month": counter.month,
                "message_count": counter.messages_sent,
                "tokens_used": counter.tokens_used,
                "updated_at": counter.updated_at
            }
            for counter in counters
        ]
    
    async def reset_monthly_counter(self, workspace_id: str, month: str) -> bool:
        """
        Reset usage counter for a specific month
        Used for testing or manual resets
        
        Args:
            workspace_id: Workspace ID
            month: Month in YYYY-MM format
        
        Returns:
            True if counter was reset, False if not found
        """
        stmt = update(UsageCounter).where(
            UsageCounter.workspace_id == workspace_id,
            UsageCounter.month == month
        ).values(
            messages_sent=0,
            tokens_used=0,
            updated_at=datetime.now(timezone.utc)
        )
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.rowcount > 0
    
    async def get_workspace_total_usage(self, workspace_id: str) -> Dict[str, int]:
        """
        Get total usage across all months for a workspace
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            Dict with total usage statistics
        """
        result = await self.db.execute(
            select(
                UsageCounter.workspace_id,
                func.sum(UsageCounter.messages_sent).label('total_messages'),
                func.sum(UsageCounter.tokens_used).label('total_tokens')
            )
            .where(UsageCounter.workspace_id == workspace_id)
            .group_by(UsageCounter.workspace_id)
        )
        
        row = result.first()
        if not row:
            return {
                "total_messages": 0,
                "total_tokens": 0
            }
        
        return {
            "total_messages": row.total_messages or 0,
            "total_tokens": row.total_tokens or 0
        }


# ─── Convenience Functions ────────────────────────────────────────────────────

async def track_message_usage(
    db: AsyncSession,
    workspace_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0
) -> Dict[str, int]:
    """
    Convenience function to track message usage
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        input_tokens: Input tokens consumed
        output_tokens: Output tokens consumed
    
    Returns:
        Updated usage statistics for current month
    """
    tracker = UsageTracker(db)
    counter = await tracker.increment_message_count(
        workspace_id=workspace_id,
        count=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )
    
    return {
        "message_count": counter.messages_sent,
        "tokens_used": counter.tokens_used
    }


async def get_current_usage(db: AsyncSession, workspace_id: str) -> Dict[str, int]:
    """
    Get current month usage for a workspace
    
    Args:
        db: Database session
        workspace_id: Workspace ID
    
    Returns:
        Current month usage statistics
    """
    tracker = UsageTracker(db)
    return await tracker.get_monthly_usage(workspace_id)


async def check_token_limit(
    db: AsyncSession,
    workspace_id: str,
    estimated_tokens: int,
    tier_limits: Dict[str, int]
) -> bool:
    """
    Check if processing additional tokens would exceed monthly limit
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        estimated_tokens: Estimated tokens for the operation
        tier_limits: Tier limits dict with 'monthly_messages' key
    
    Returns:
        True if within limits, False if would exceed
    """
    tracker = UsageTracker(db)
    current_usage = await tracker.get_monthly_usage(workspace_id)
    
    # For now, we use message count as the primary limit
    # Token limits could be added to tier configuration in the future
    return current_usage["message_count"] < tier_limits.get("monthly_messages", 0)