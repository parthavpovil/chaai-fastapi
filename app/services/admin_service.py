"""
Platform Administration Service
Super admin access control and platform management
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.user import User
from app.models.workspace import Workspace
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.usage_counter import UsageCounter
from app.models.tier_change import TierChange


class AdminService:
    """Platform administration service for super admin operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    def is_super_admin(self, user_email: str) -> bool:
        """
        Check if user email matches super admin email
        
        Args:
            user_email: User email to check
            
        Returns:
            True if user is super admin
        """
        return user_email.lower() == settings.SUPER_ADMIN_EMAIL.lower()
    
    async def get_platform_overview(self) -> Dict[str, Any]:
        """
        Get platform overview with workspace statistics and activity metrics
        
        Returns:
            Dictionary with platform statistics
        """
        # Get workspace counts by tier
        tier_result = await self.db.execute(
            select(
                Workspace.tier,
                func.count(Workspace.id).label('count')
            )
            .group_by(Workspace.tier)
        )
        tier_breakdown = {row.tier: row.count for row in tier_result}
        
        # Get total workspace count
        total_workspaces_result = await self.db.execute(
            select(func.count(Workspace.id))
        )
        total_workspaces = total_workspaces_result.scalar() or 0
        
        # Get total user count
        total_users_result = await self.db.execute(
            select(func.count(User.id))
        )
        total_users = total_users_result.scalar() or 0
        
        # Get active user count (users who logged in within last 30 days)
        thirty_days_ago = datetime.now(timezone.utc).replace(day=1)  # Start of current month
        active_users_result = await self.db.execute(
            select(func.count(User.id))
            .where(User.last_login >= thirty_days_ago)
        )
        active_users = active_users_result.scalar() or 0
        
        # Get message statistics for current month
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        message_stats_result = await self.db.execute(
            select(
                func.sum(UsageCounter.messages_sent).label('total_messages'),
                func.sum(UsageCounter.tokens_used).label('total_tokens')
            )
            .where(UsageCounter.month == current_month)
        )
        message_stats = message_stats_result.first()
        total_messages = message_stats.total_messages or 0 if message_stats else 0
        total_tokens = message_stats.total_tokens or 0 if message_stats else 0
        
        # Get recent activity (workspaces created in last 7 days)
        seven_days_ago = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = seven_days_ago.replace(day=seven_days_ago.day - 7)
        
        recent_signups_result = await self.db.execute(
            select(func.count(Workspace.id))
            .where(Workspace.created_at >= seven_days_ago)
        )
        recent_signups = recent_signups_result.scalar() or 0
        
        return {
            "total_workspaces": total_workspaces,
            "total_users": total_users,
            "active_users": active_users,
            "tier_breakdown": tier_breakdown,
            "current_month_stats": {
                "total_messages": total_messages,
                "total_tokens": total_tokens,
                "month": current_month
            },
            "recent_activity": {
                "signups_last_7_days": recent_signups
            }
        }
    
    async def get_workspace_list(
        self, 
        limit: int = 50, 
        offset: int = 0,
        tier_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get paginated list of workspaces with owner information
        
        Args:
            limit: Maximum number of workspaces to return
            offset: Offset for pagination
            tier_filter: Optional tier filter
            
        Returns:
            List of workspace dictionaries
        """
        query = (
            select(Workspace, User)
            .join(User, Workspace.owner_id == User.id)
            .order_by(desc(Workspace.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        if tier_filter:
            query = query.where(Workspace.tier == tier_filter)
        
        result = await self.db.execute(query)
        workspaces = []
        
        for workspace, owner in result:
            workspaces.append({
                "id": str(workspace.id),
                "name": workspace.name,
                "slug": workspace.slug,
                "tier": workspace.tier,
                "owner_email": owner.email,
                "owner_active": owner.is_active,
                "created_at": workspace.created_at.isoformat(),
                "tier_changed_at": workspace.tier_changed_at.isoformat() if workspace.tier_changed_at else None,
                "tier_changed_by": workspace.tier_changed_by
            })
        
        return workspaces
    
    async def get_user_list(
        self, 
        limit: int = 50, 
        offset: int = 0,
        active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get paginated list of users with workspace information
        
        Args:
            limit: Maximum number of users to return
            offset: Offset for pagination
            active_only: Only return active users
            
        Returns:
            List of user dictionaries
        """
        query = (
            select(User)
            .options(selectinload(User.owned_workspaces))
            .order_by(desc(User.created_at))
            .limit(limit)
            .offset(offset)
        )
        
        if active_only:
            query = query.where(User.is_active == True)
        
        result = await self.db.execute(query)
        users = []
        
        for user in result.scalars():
            workspace = user.owned_workspaces[0] if user.owned_workspaces else None
            users.append({
                "id": str(user.id),
                "email": user.email,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat(),
                "last_login": user.last_login.isoformat() if user.last_login else None,
                "workspace": {
                    "id": str(workspace.id),
                    "name": workspace.name,
                    "slug": workspace.slug,
                    "tier": workspace.tier
                } if workspace else None
            })
        
        return users
    
    async def suspend_user(self, user_id: UUID, admin_email: str) -> bool:
        """
        Suspend a user account
        
        Args:
            user_id: User ID to suspend
            admin_email: Admin email for verification
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If not super admin or user not found
        """
        if not self.is_super_admin(admin_email):
            raise ValueError("Unauthorized: Only super admin can suspend users")
        
        # Find user
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            raise ValueError("User not found")
        
        if not user.is_active:
            raise ValueError("User is already suspended")
        
        # Suspend user
        user.is_active = False
        await self.db.commit()
        
        return True
    
    async def unsuspend_user(self, user_id: UUID, admin_email: str) -> bool:
        """
        Unsuspend a user account
        
        Args:
            user_id: User ID to unsuspend
            admin_email: Admin email for verification
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If not super admin or user not found
        """
        if not self.is_super_admin(admin_email):
            raise ValueError("Unauthorized: Only super admin can unsuspend users")
        
        # Find user
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            raise ValueError("User not found")
        
        if user.is_active:
            raise ValueError("User is already active")
        
        # Unsuspend user
        user.is_active = True
        await self.db.commit()
        
        return True
    
    async def change_workspace_tier(
        self, 
        workspace_id: UUID, 
        new_tier: str, 
        admin_email: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Change workspace tier with audit logging
        
        Args:
            workspace_id: Workspace ID
            new_tier: New tier (free, starter, growth, pro)
            admin_email: Admin email for verification
            reason: Optional reason for tier change
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If not super admin, workspace not found, or invalid tier
        """
        if not self.is_super_admin(admin_email):
            raise ValueError("Unauthorized: Only super admin can change tiers")
        
        valid_tiers = ["free", "starter", "growth", "pro"]
        if new_tier not in valid_tiers:
            raise ValueError(f"Invalid tier. Must be one of: {', '.join(valid_tiers)}")
        
        # Find workspace
        result = await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()
        
        if not workspace:
            raise ValueError("Workspace not found")
        
        if workspace.tier == new_tier:
            raise ValueError(f"Workspace is already on {new_tier} tier")
        
        # Record tier change for audit
        tier_change = TierChange(
            workspace_id=workspace_id,
            from_tier=workspace.tier,
            to_tier=new_tier,
            changed_by=admin_email,
            note=reason or f"Tier changed by admin {admin_email}"
        )
        self.db.add(tier_change)
        
        # Update workspace tier
        workspace.tier = new_tier
        workspace.tier_changed_at = datetime.now(timezone.utc)
        workspace.tier_changed_by = admin_email
        
        await self.db.commit()
        
        return True
    
    async def get_tier_change_history(
        self, 
        workspace_id: Optional[UUID] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get tier change history with audit information
        
        Args:
            workspace_id: Optional workspace ID filter
            limit: Maximum number of records to return
            
        Returns:
            List of tier change records
        """
        query = (
            select(TierChange, Workspace)
            .join(Workspace, TierChange.workspace_id == Workspace.id)
            .order_by(desc(TierChange.created_at))
            .limit(limit)
        )
        
        if workspace_id:
            query = query.where(TierChange.workspace_id == workspace_id)
        
        result = await self.db.execute(query)
        changes = []
        
        for tier_change, workspace in result:
            changes.append({
                "id": str(tier_change.id),
                "workspace_id": str(tier_change.workspace_id),
                "workspace_name": workspace.name,
                "workspace_slug": workspace.slug,
                "from_tier": tier_change.from_tier,
                "to_tier": tier_change.to_tier,
                "changed_by": tier_change.changed_by,
                "note": tier_change.note,
                "created_at": tier_change.created_at.isoformat()
            })
        
        return changes
    async def delete_workspace(
        self, 
        workspace_id: UUID, 
        confirmation_name: str,
        admin_email: str
    ) -> bool:
        """
        Delete workspace with name confirmation for safety
        
        Args:
            workspace_id: Workspace ID to delete
            confirmation_name: Workspace name for confirmation
            admin_email: Admin email for verification
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If not super admin, workspace not found, or name mismatch
        """
        if not self.is_super_admin(admin_email):
            raise ValueError("Unauthorized: Only super admin can delete workspaces")
        
        # Find workspace
        result = await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()
        
        if not workspace:
            raise ValueError("Workspace not found")
        
        # Verify name confirmation
        if workspace.name != confirmation_name:
            raise ValueError("Workspace name confirmation does not match")
        
        # Delete workspace (cascade will handle related records)
        await self.db.delete(workspace)
        await self.db.commit()
        
        return True

    async def get_analytics_dashboard(self) -> Dict[str, Any]:
        """
        Get analytics dashboard with message volume, signup trends, and escalation statistics
        
        Returns:
            Dictionary with analytics data
        """
        # Get message volume trends (last 12 months)
        current_date = datetime.now(timezone.utc)
        months = []
        for i in range(12):
            month_date = current_date.replace(day=1) - timedelta(days=30 * i)
            months.append(month_date.strftime("%Y-%m"))
        
        # Get message volume by month
        message_volume_result = await self.db.execute(
            select(
                UsageCounter.month,
                func.sum(UsageCounter.messages_sent).label('messages'),
                func.sum(UsageCounter.tokens_used).label('tokens')
            )
            .where(UsageCounter.month.in_(months))
            .group_by(UsageCounter.month)
            .order_by(UsageCounter.month)
        )
        
        message_volume = {}
        for row in message_volume_result:
            message_volume[row.month] = {
                'messages': row.messages or 0,
                'tokens': row.tokens or 0
            }
        
        # Fill in missing months with zeros
        for month in months:
            if month not in message_volume:
                message_volume[month] = {'messages': 0, 'tokens': 0}
        
        # Get signup trends (last 12 months)
        signup_trends = {}
        for month in months:
            month_start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1)
            
            signup_result = await self.db.execute(
                select(func.count(Workspace.id))
                .where(
                    and_(
                        Workspace.created_at >= month_start,
                        Workspace.created_at < month_end
                    )
                )
            )
            signup_trends[month] = signup_result.scalar() or 0
        
        # Get escalation statistics
        escalation_result = await self.db.execute(
            select(func.count(Conversation.id))
            .where(Conversation.status.in_(['escalated', 'agent']))
        )
        total_escalations = escalation_result.scalar() or 0
        
        # Get total conversations for escalation rate
        total_conversations_result = await self.db.execute(
            select(func.count(Conversation.id))
        )
        total_conversations = total_conversations_result.scalar() or 0
        
        escalation_rate = (total_escalations / total_conversations * 100) if total_conversations > 0 else 0
        
        # Get current month statistics
        current_month = current_date.strftime("%Y-%m")
        current_month_messages = message_volume.get(current_month, {'messages': 0, 'tokens': 0})
        current_month_signups = signup_trends.get(current_month, 0)
        
        return {
            "message_volume": {
                "monthly_data": message_volume,
                "current_month": current_month_messages,
                "trend_months": sorted(months, reverse=True)
            },
            "signup_trends": {
                "monthly_data": signup_trends,
                "current_month": current_month_signups,
                "trend_months": sorted(months, reverse=True)
            },
            "escalation_statistics": {
                "total_escalations": total_escalations,
                "total_conversations": total_conversations,
                "escalation_rate": round(escalation_rate, 2)
            }
        }