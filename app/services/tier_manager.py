"""
Tier Management Service
Handles tier limits, usage tracking, and feature access control
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import TIER_LIMITS
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.agent import Agent
from app.models.document import Document
from app.models.usage_counter import UsageCounter


class TierLimitError(Exception):
    """Raised when a tier limit is exceeded"""
    pass


class TierManager:
    """
    Manages tier limits and usage tracking for workspaces
    Enforces limits on channels, agents, documents, and monthly messages
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_workspace_tier_info(self, workspace_id: str) -> Dict[str, Any]:
        """
        Get complete tier information for a workspace
        
        Returns:
            Dict containing tier, limits, and current usage
        """
        # Get workspace
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")
        
        tier = workspace.tier
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
        
        # Get current usage
        usage = await self._get_current_usage(workspace_id)
        
        return {
            "tier": tier,
            "limits": limits,
            "usage": usage,
            "remaining": {
                "channels": max(0, limits["channels"] - usage["channels"]),
                "agents": max(0, limits["agents"] - usage["agents"]),
                "documents": max(0, limits["documents_max"] - usage["documents"]),
                "monthly_messages": max(0, limits["monthly_messages"] - usage["monthly_messages"])
            }
        }
    
    async def _get_current_usage(self, workspace_id: str) -> Dict[str, int]:
        """Get current usage counts for a workspace"""
        
        # Count channels
        channels_result = await self.db.execute(
            select(func.count(Channel.id))
            .where(Channel.workspace_id == workspace_id)
        )
        channels_count = channels_result.scalar() or 0
        
        # Count agents
        agents_result = await self.db.execute(
            select(func.count(Agent.id))
            .where(Agent.workspace_id == workspace_id)
            .where(Agent.is_active == True)
        )
        agents_count = agents_result.scalar() or 0
        
        # Count documents
        documents_result = await self.db.execute(
            select(func.count(Document.id))
            .where(Document.workspace_id == workspace_id)
        )
        documents_count = documents_result.scalar() or 0
        
        # Get monthly message usage
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage_result = await self.db.execute(
            select(UsageCounter.message_count)
            .where(UsageCounter.workspace_id == workspace_id)
            .where(UsageCounter.month == current_month)
        )
        monthly_messages = usage_result.scalar() or 0
        
        return {
            "channels": channels_count,
            "agents": agents_count,
            "documents": documents_count,
            "monthly_messages": monthly_messages
        }
    
    async def check_channel_limit(self, workspace_id: str) -> bool:
        """
        Check if workspace can create another channel
        
        Returns:
            True if within limit, False if at limit
        
        Raises:
            TierLimitError: If limit would be exceeded
        """
        tier_info = await self.get_workspace_tier_info(workspace_id)
        
        if tier_info["usage"]["channels"] >= tier_info["limits"]["channels"]:
            raise TierLimitError(
                f"Channel limit reached for {tier_info['tier']} tier "
                f"({tier_info['limits']['channels']} channels maximum)"
            )
        
        return True
    
    async def check_agent_limit(self, workspace_id: str) -> bool:
        """
        Check if workspace can add another agent
        
        Returns:
            True if within limit, False if at limit
        
        Raises:
            TierLimitError: If limit would be exceeded
        """
        tier_info = await self.get_workspace_tier_info(workspace_id)
        
        if tier_info["usage"]["agents"] >= tier_info["limits"]["agents"]:
            raise TierLimitError(
                f"Agent limit reached for {tier_info['tier']} tier "
                f"({tier_info['limits']['agents']} agents maximum)"
            )
        
        return True
    
    async def check_document_limit(self, workspace_id: str) -> bool:
        """
        Check if workspace can upload another document
        
        Returns:
            True if within limit, False if at limit
        
        Raises:
            TierLimitError: If limit would be exceeded
        """
        tier_info = await self.get_workspace_tier_info(workspace_id)
        
        if tier_info["usage"]["documents"] >= tier_info["limits"]["documents_max"]:
            raise TierLimitError(
                f"Document limit reached for {tier_info['tier']} tier "
                f"({tier_info['limits']['documents_max']} documents maximum)"
            )
        
        return True
    
    async def check_monthly_message_limit(self, workspace_id: str, additional_messages: int = 1) -> bool:
        """
        Check if workspace can process additional messages this month
        
        Args:
            workspace_id: Workspace ID
            additional_messages: Number of additional messages to check
        
        Returns:
            True if within limit, False if at limit
        
        Raises:
            TierLimitError: If limit would be exceeded
        """
        tier_info = await self.get_workspace_tier_info(workspace_id)
        
        new_total = tier_info["usage"]["monthly_messages"] + additional_messages
        
        if new_total > tier_info["limits"]["monthly_messages"]:
            raise TierLimitError(
                f"Monthly message limit reached for {tier_info['tier']} tier "
                f"({tier_info['limits']['monthly_messages']} messages maximum)"
            )
        
        return True
    
    async def has_feature_access(self, workspace_id: str, feature: str) -> bool:
        """
        Check if workspace has access to a specific feature
        
        Args:
            workspace_id: Workspace ID
            feature: Feature name ('agents', 'advanced_analytics', etc.)
        
        Returns:
            True if feature is available for this tier
        """
        tier_info = await self.get_workspace_tier_info(workspace_id)
        tier = tier_info["tier"]
        
        # Feature access rules based on tier
        feature_access = {
            "agents": tier in ["pro"],
            "advanced_analytics": tier in ["growth", "pro"],
            "priority_support": tier in ["pro"],
            "custom_branding": tier in ["pro"],
            "api_access": tier in ["growth", "pro"],
            "webhook_retries": tier in ["growth", "pro"],
        }
        
        return feature_access.get(feature, False)
    
    async def get_tier_upgrade_suggestions(self, workspace_id: str) -> Dict[str, Any]:
        """
        Get tier upgrade suggestions based on current usage
        
        Returns:
            Dict with upgrade recommendations and benefits
        """
        tier_info = await self.get_workspace_tier_info(workspace_id)
        current_tier = tier_info["tier"]
        usage = tier_info["usage"]
        
        # Find bottlenecks
        bottlenecks = []
        if tier_info["remaining"]["channels"] <= 0:
            bottlenecks.append("channels")
        if tier_info["remaining"]["agents"] <= 0:
            bottlenecks.append("agents")
        if tier_info["remaining"]["documents"] <= 0:
            bottlenecks.append("documents")
        if tier_info["remaining"]["monthly_messages"] <= 100:  # Close to limit
            bottlenecks.append("monthly_messages")
        
        # Suggest next tier
        tier_order = ["free", "starter", "growth", "pro"]
        current_index = tier_order.index(current_tier) if current_tier in tier_order else 0
        
        suggested_tier = None
        if current_index < len(tier_order) - 1:
            suggested_tier = tier_order[current_index + 1]
        
        return {
            "current_tier": current_tier,
            "suggested_tier": suggested_tier,
            "bottlenecks": bottlenecks,
            "usage_percentage": {
                "channels": (usage["channels"] / tier_info["limits"]["channels"]) * 100,
                "agents": (usage["agents"] / tier_info["limits"]["agents"]) * 100 if tier_info["limits"]["agents"] > 0 else 0,
                "documents": (usage["documents"] / tier_info["limits"]["documents_max"]) * 100,
                "monthly_messages": (usage["monthly_messages"] / tier_info["limits"]["monthly_messages"]) * 100
            }
        }


# ─── Convenience Functions ────────────────────────────────────────────────────

async def check_workspace_limits(
    db: AsyncSession, 
    workspace_id: str, 
    resource_type: str,
    additional_count: int = 1
) -> bool:
    """
    Convenience function to check workspace limits for any resource type
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        resource_type: Type of resource ('channels', 'agents', 'documents', 'messages')
        additional_count: Number of additional resources to check
    
    Returns:
        True if within limits
    
    Raises:
        TierLimitError: If limit would be exceeded
    """
    tier_manager = TierManager(db)
    
    if resource_type == "channels":
        return await tier_manager.check_channel_limit(workspace_id)
    elif resource_type == "agents":
        return await tier_manager.check_agent_limit(workspace_id)
    elif resource_type == "documents":
        return await tier_manager.check_document_limit(workspace_id)
    elif resource_type == "messages":
        return await tier_manager.check_monthly_message_limit(workspace_id, additional_count)
    else:
        raise ValueError(f"Unknown resource type: {resource_type}")


async def get_workspace_tier_summary(db: AsyncSession, workspace_id: str) -> Dict[str, Any]:
    """
    Get a summary of workspace tier and usage for dashboard display
    """
    tier_manager = TierManager(db)
    return await tier_manager.get_workspace_tier_info(workspace_id)