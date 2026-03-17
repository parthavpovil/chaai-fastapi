"""
Rate Limiting Service
Database-backed rate limiting for WebChat sessions and API endpoints
"""
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from sqlalchemy.dialects.postgresql import insert

from app.models.rate_limit import RateLimit


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded"""
    pass


class RateLimiter:
    """
    Database-backed rate limiter with configurable limits
    Supports different rate limiting strategies and automatic cleanup
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def check_rate_limit(
        self,
        identifier: str,
        limit_type: str,
        max_requests: int,
        window_minutes: int,
        workspace_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is within rate limit
        
        Args:
            identifier: Unique identifier (IP, session token, user ID, etc.)
            limit_type: Type of rate limit (webchat, api, etc.)
            max_requests: Maximum requests allowed in window
            window_minutes: Time window in minutes
            workspace_id: Optional workspace ID for isolation
        
        Returns:
            Tuple of (is_allowed, rate_limit_info)
        
        Raises:
            RateLimitExceededError: If rate limit exceeded
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=window_minutes)
        
        # Get or create rate limit record
        rate_limit = await self._get_or_create_rate_limit(
            identifier, limit_type, workspace_id
        )
        
        # Clean up old requests outside the window
        await self._cleanup_old_requests(rate_limit.id, window_start)
        
        # Count requests in current window
        current_count = len([
            req for req in rate_limit.request_timestamps
            if req >= window_start
        ])
        
        # Check if limit exceeded
        if current_count >= max_requests:
            # Calculate reset time
            oldest_request = min(rate_limit.request_timestamps) if rate_limit.request_timestamps else now
            reset_time = oldest_request + timedelta(minutes=window_minutes)
            
            rate_limit_info = {
                "allowed": False,
                "limit": max_requests,
                "remaining": 0,
                "reset_time": reset_time.isoformat(),
                "retry_after_seconds": int((reset_time - now).total_seconds())
            }
            
            return False, rate_limit_info
        
        # Add current request timestamp
        rate_limit.request_timestamps.append(now)
        rate_limit.updated_at = now
        
        await self.db.commit()
        
        rate_limit_info = {
            "allowed": True,
            "limit": max_requests,
            "remaining": max_requests - current_count - 1,
            "reset_time": (now + timedelta(minutes=window_minutes)).isoformat(),
            "retry_after_seconds": 0
        }
        
        return True, rate_limit_info
    
    async def _get_or_create_rate_limit(
        self,
        identifier: str,
        limit_type: str,
        workspace_id: Optional[str] = None
    ) -> RateLimit:
        """
        Get existing rate limit record or create new one
        
        Args:
            identifier: Rate limit identifier
            limit_type: Type of rate limit
            workspace_id: Optional workspace ID
        
        Returns:
            RateLimit instance
        """
        # Try to get existing record
        query = select(RateLimit).where(
            and_(
                RateLimit.identifier == identifier,
                RateLimit.limit_type == limit_type
            )
        )
        
        if workspace_id:
            query = query.where(RateLimit.workspace_id == workspace_id)
        else:
            query = query.where(RateLimit.workspace_id.is_(None))
        
        result = await self.db.execute(query)
        rate_limit = result.scalar_one_or_none()
        
        if rate_limit:
            return rate_limit
        
        # Create new rate limit record
        rate_limit = RateLimit(
            identifier=identifier,
            limit_type=limit_type,
            workspace_id=workspace_id,
            request_timestamps=[]
        )
        
        self.db.add(rate_limit)
        await self.db.commit()
        await self.db.refresh(rate_limit)
        
        return rate_limit
    
    async def _cleanup_old_requests(self, rate_limit_id: str, window_start: datetime):
        """
        Remove old request timestamps outside the current window
        
        Args:
            rate_limit_id: Rate limit record ID
            window_start: Start of current window
        """
        result = await self.db.execute(
            select(RateLimit).where(RateLimit.id == rate_limit_id)
        )
        rate_limit = result.scalar_one()
        
        # Filter out old timestamps
        rate_limit.request_timestamps = [
            ts for ts in rate_limit.request_timestamps
            if ts >= window_start
        ]
        
        await self.db.commit()
    
    async def reset_rate_limit(
        self,
        identifier: str,
        limit_type: str,
        workspace_id: Optional[str] = None
    ) -> bool:
        """
        Reset rate limit for identifier
        
        Args:
            identifier: Rate limit identifier
            limit_type: Type of rate limit
            workspace_id: Optional workspace ID
        
        Returns:
            True if reset successfully
        """
        query = select(RateLimit).where(
            and_(
                RateLimit.identifier == identifier,
                RateLimit.limit_type == limit_type
            )
        )
        
        if workspace_id:
            query = query.where(RateLimit.workspace_id == workspace_id)
        else:
            query = query.where(RateLimit.workspace_id.is_(None))
        
        result = await self.db.execute(query)
        rate_limit = result.scalar_one_or_none()
        
        if rate_limit:
            rate_limit.request_timestamps = []
            rate_limit.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            return True
        
        return False
    
    async def cleanup_expired_records(self, max_age_hours: int = 24) -> int:
        """
        Clean up old rate limit records
        
        Args:
            max_age_hours: Maximum age of records to keep
        
        Returns:
            Number of records cleaned up
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        stmt = delete(RateLimit).where(RateLimit.updated_at < cutoff_time)
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.rowcount
    
    async def get_rate_limit_stats(
        self,
        limit_type: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get rate limiting statistics
        
        Args:
            limit_type: Optional filter by limit type
            workspace_id: Optional filter by workspace
        
        Returns:
            Rate limiting statistics
        """
        from sqlalchemy import func
        
        query = select(
            func.count(RateLimit.id).label('total_records'),
            func.count(func.distinct(RateLimit.identifier)).label('unique_identifiers'),
            func.avg(func.array_length(RateLimit.request_timestamps, 1)).label('avg_requests')
        )
        
        if limit_type:
            query = query.where(RateLimit.limit_type == limit_type)
        
        if workspace_id:
            query = query.where(RateLimit.workspace_id == workspace_id)
        
        result = await self.db.execute(query)
        row = result.first()
        
        return {
            "total_records": row.total_records or 0,
            "unique_identifiers": row.unique_identifiers or 0,
            "average_requests_per_identifier": float(row.avg_requests or 0),
            "filter": {
                "limit_type": limit_type,
                "workspace_id": workspace_id
            }
        }


class WebChatRateLimiter:
    """
    Specialized rate limiter for WebChat sessions
    Implements 10 messages per minute limit with session token management
    """
    
    def __init__(self, db: AsyncSession):
        self.rate_limiter = RateLimiter(db)
        self.max_messages = 10
        self.window_minutes = 1
    
    async def check_webchat_limit(
        self,
        session_token: str,
        workspace_id: str
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check WebChat rate limit for session
        
        Args:
            session_token: WebChat session token
            workspace_id: Workspace ID
        
        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        return await self.rate_limiter.check_rate_limit(
            identifier=session_token,
            limit_type="webchat",
            max_requests=self.max_messages,
            window_minutes=self.window_minutes,
            workspace_id=workspace_id
        )
    
    async def enforce_webchat_limit(
        self,
        session_token: str,
        workspace_id: str
    ) -> Dict[str, Any]:
        """
        Enforce WebChat rate limit and raise exception if exceeded
        
        Args:
            session_token: WebChat session token
            workspace_id: Workspace ID
        
        Returns:
            Rate limit information
        
        Raises:
            RateLimitExceededError: If rate limit exceeded
        """
        is_allowed, rate_info = await self.check_webchat_limit(session_token, workspace_id)
        
        if not is_allowed:
            raise RateLimitExceededError(
                f"Rate limit exceeded: {self.max_messages} messages per minute. "
                f"Try again in {rate_info['retry_after_seconds']} seconds."
            )
        
        return rate_info


class APIRateLimiter:
    """
    Rate limiter for API endpoints
    Configurable limits based on endpoint and user type
    """
    
    def __init__(self, db: AsyncSession):
        self.rate_limiter = RateLimiter(db)
    
    async def check_api_limit(
        self,
        identifier: str,
        endpoint: str,
        max_requests: int = 100,
        window_minutes: int = 60,
        workspace_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check API rate limit
        
        Args:
            identifier: User/IP identifier
            endpoint: API endpoint
            max_requests: Maximum requests allowed
            window_minutes: Time window in minutes
            workspace_id: Optional workspace ID
        
        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        limit_type = f"api_{endpoint}"
        
        return await self.rate_limiter.check_rate_limit(
            identifier=identifier,
            limit_type=limit_type,
            max_requests=max_requests,
            window_minutes=window_minutes,
            workspace_id=workspace_id
        )


# ─── Convenience Functions ────────────────────────────────────────────────────

async def check_webchat_rate_limit(
    db: AsyncSession,
    session_token: str,
    workspace_id: str
) -> Dict[str, Any]:
    """
    Convenience function to check WebChat rate limit
    
    Args:
        db: Database session
        session_token: WebChat session token
        workspace_id: Workspace ID
    
    Returns:
        Rate limit information
    
    Raises:
        RateLimitExceededError: If rate limit exceeded
    """
    limiter = WebChatRateLimiter(db)
    return await limiter.enforce_webchat_limit(session_token, workspace_id)


async def check_api_rate_limit(
    db: AsyncSession,
    identifier: str,
    endpoint: str,
    max_requests: int = 100,
    window_minutes: int = 60,
    workspace_id: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Convenience function to check API rate limit
    
    Args:
        db: Database session
        identifier: User/IP identifier
        endpoint: API endpoint
        max_requests: Maximum requests allowed
        window_minutes: Time window in minutes
        workspace_id: Optional workspace ID
    
    Returns:
        Tuple of (is_allowed, rate_limit_info)
    """
    limiter = APIRateLimiter(db)
    return await limiter.check_api_limit(
        identifier, endpoint, max_requests, window_minutes, workspace_id
    )


async def cleanup_rate_limit_records(db: AsyncSession, max_age_hours: int = 24) -> int:
    """
    Clean up old rate limit records
    
    Args:
        db: Database session
        max_age_hours: Maximum age of records to keep
    
    Returns:
        Number of records cleaned up
    """
    limiter = RateLimiter(db)
    return await limiter.cleanup_expired_records(max_age_hours)