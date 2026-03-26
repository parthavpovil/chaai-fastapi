"""
Agent Management Service
Handles agent invitations, acceptance, and lifecycle management
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

logger = logging.getLogger(__name__)

from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.user import User
from app.services.tier_manager import TierManager, TierLimitError
from app.services.webhook_security import generate_invitation_token


class AgentManagementError(Exception):
    """Base exception for agent management errors"""
    pass


class AgentManager:
    """
    Service for managing agent invitations and lifecycle
    Handles pro tier limits and secure token generation
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.tier_manager = TierManager(db)
    
    async def create_agent_invitation(
        self,
        workspace_id: str,
        email: str,
        name: str,
        invited_by_user_id: str
    ) -> Agent:
        """
        Create agent invitation with secure token
        
        Args:
            workspace_id: Workspace ID
            email: Agent email address
            name: Agent name
            invited_by_user_id: User ID who sent the invitation
        
        Returns:
            Created Agent instance with invitation token
        
        Raises:
            AgentManagementError: If invitation creation fails
            TierLimitError: If agent limit exceeded
        """
        try:
            # Check tier limits (only pro tier can have agents)
            await self.tier_manager.check_agent_limit(workspace_id)
            
            # Check if agent with this email already exists in workspace
            existing_agent = await self.get_agent_by_email(workspace_id, email)
            if existing_agent:
                raise AgentManagementError(f"Agent with email {email} already exists in this workspace")
            
            # Generate secure invitation token (7-day expiration)
            invitation_token = generate_invitation_token()
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            
            # Create agent record
            agent = Agent(
                workspace_id=workspace_id,
                email=email,
                name=name,
                invitation_token=invitation_token,
                invitation_expires_at=expires_at,
                is_active=False  # Not active until invitation is accepted
            )
            
            self.db.add(agent)
            await self.db.commit()
            await self.db.refresh(agent)
            
            return agent
            
        except TierLimitError:
            raise
        except Exception as e:
            await self.db.rollback()
            raise AgentManagementError(f"Failed to create agent invitation: {str(e)}")
    
    async def get_agent_by_email(self, workspace_id: str, email: str) -> Optional[Agent]:
        """
        Get agent by email within workspace
        
        Args:
            workspace_id: Workspace ID
            email: Agent email
        
        Returns:
            Agent instance or None
        """
        result = await self.db.execute(
            select(Agent)
            .where(Agent.workspace_id == workspace_id)
            .where(Agent.email == email)
        )
        return result.scalar_one_or_none()
    
    async def get_agent_by_token(self, invitation_token: str) -> Optional[Agent]:
        """
        Get agent by invitation token
        
        Args:
            invitation_token: Invitation token
        
        Returns:
            Agent instance or None if token invalid/expired
        """
        result = await self.db.execute(
            select(Agent)
            .where(Agent.invitation_token == invitation_token)
            .where(Agent.invitation_expires_at > datetime.now(timezone.utc))
            .where(Agent.user_id.is_(None))  # Not yet accepted
        )
        return result.scalar_one_or_none()
    
    async def accept_agent_invitation(
        self,
        invitation_token: str,
        user_id: str
    ) -> Agent:
        """
        Accept agent invitation and link to user account
        
        Args:
            invitation_token: Invitation token
            user_id: User ID accepting the invitation
        
        Returns:
            Updated Agent instance
        
        Raises:
            AgentManagementError: If acceptance fails
        """
        try:
            # Get agent by token
            agent = await self.get_agent_by_token(invitation_token)
            if not agent:
                raise AgentManagementError("Invalid or expired invitation token")
            
            # Verify user exists
            user_result = await self.db.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                raise AgentManagementError("User not found")
            
            # Check if user email matches agent email
            if user.email.lower() != agent.email.lower():
                raise AgentManagementError("User email does not match invitation email")
            
            # Update agent record
            agent.user_id = user_id
            agent.is_active = True
            agent.invitation_accepted_at = datetime.now(timezone.utc)
            agent.invitation_token = None  # Clear token after acceptance
            agent.invitation_expires_at = None
            
            await self.db.commit()
            await self.db.refresh(agent)
            
            return agent
            
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, AgentManagementError):
                raise
            raise AgentManagementError(f"Failed to accept invitation: {str(e)}")
    
    async def deactivate_agent(
        self,
        agent_id: str,
        workspace_id: str,
        deactivated_by_user_id: str
    ) -> Agent:
        """
        Deactivate agent and update conversations
        
        Args:
            agent_id: Agent ID
            workspace_id: Workspace ID for verification
            deactivated_by_user_id: User ID who deactivated the agent
        
        Returns:
            Updated Agent instance
        
        Raises:
            AgentManagementError: If deactivation fails
        """
        try:
            # Get agent
            result = await self.db.execute(
                select(Agent)
                .where(Agent.id == agent_id)
                .where(Agent.workspace_id == workspace_id)
            )
            agent = result.scalar_one_or_none()
            if not agent:
                raise AgentManagementError("Agent not found")
            
            # Update agent status
            agent.is_active = False
            
            # Update conversations assigned to this agent
            await self._cleanup_agent_conversations(agent_id)
            
            await self.db.commit()
            await self.db.refresh(agent)
            
            return agent
            
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, AgentManagementError):
                raise
            raise AgentManagementError(f"Failed to deactivate agent: {str(e)}")
    
    async def _cleanup_agent_conversations(self, agent_id: str):
        """
        Update conversations from 'agent' to 'escalated' status when agent is deactivated
        
        Args:
            agent_id: Agent ID
        """
        from app.models.conversation import Conversation
        from sqlalchemy import update, select
        
        # First get the conversations that will be affected
        result = await self.db.execute(
            select(Conversation.id, Conversation.workspace_id)
            .where(
                and_(
                    Conversation.assigned_agent_id == agent_id,
                    Conversation.status == "agent"
                )
            )
        )
        affected_conversations = result.fetchall()
        
        # Update conversations assigned to this agent
        stmt = update(Conversation).where(
            and_(
                Conversation.assigned_agent_id == agent_id,
                Conversation.status == "agent"
            )
        ).values(
            status="escalated",
            assigned_agent_id=None,
            updated_at=datetime.now(timezone.utc)
        )
        
        await self.db.execute(stmt)
        
        # Send WebSocket notifications for each affected conversation
        from app.services.websocket_events import notify_conversation_status_change
        for conversation_id, workspace_id in affected_conversations:
            try:
                await notify_conversation_status_change(
                    db=self.db,
                    workspace_id=str(workspace_id),
                    conversation_id=str(conversation_id),
                    old_status="agent",
                    new_status="escalated",
                    agent_id=None
                )
            except Exception as e:
                logger.warning(f"Failed to send WebSocket notification for conversation {conversation_id}: {e}")
    
    async def get_workspace_agents(
        self,
        workspace_id: str,
        include_inactive: bool = False
    ) -> List[Agent]:
        """
        Get all agents for a workspace
        
        Args:
            workspace_id: Workspace ID
            include_inactive: Whether to include inactive agents
        
        Returns:
            List of agents
        """
        query = select(Agent).where(Agent.workspace_id == workspace_id)
        
        if not include_inactive:
            query = query.where(Agent.is_active == True)
        
        query = query.order_by(Agent.created_at)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_pending_invitations(self, workspace_id: str) -> List[Agent]:
        """
        Get pending agent invitations for workspace
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            List of agents with pending invitations
        """
        result = await self.db.execute(
            select(Agent)
            .where(Agent.workspace_id == workspace_id)
            .where(Agent.user_id.is_(None))  # Not accepted yet
            .where(Agent.invitation_expires_at > datetime.now(timezone.utc))  # Not expired
            .order_by(Agent.created_at.desc())
        )
        return result.scalars().all()
    
    async def cleanup_expired_invitations(self) -> int:
        """
        Clean up expired agent invitations
        
        Returns:
            Number of invitations cleaned up
        """
        from sqlalchemy import delete
        
        # Delete expired invitations
        stmt = delete(Agent).where(
            and_(
                Agent.user_id.is_(None),  # Not accepted
                Agent.invitation_expires_at <= datetime.now(timezone.utc)  # Expired
            )
        )
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.rowcount
    
    async def resend_agent_invitation(
        self,
        agent_id: str,
        workspace_id: str,
        resent_by_user_id: str
    ) -> Agent:
        """
        Resend agent invitation with new token
        
        Args:
            agent_id: Agent ID
            workspace_id: Workspace ID for verification
            resent_by_user_id: User ID who resent the invitation
        
        Returns:
            Updated Agent instance with new token
        
        Raises:
            AgentManagementError: If resend fails
        """
        try:
            # Get agent
            result = await self.db.execute(
                select(Agent)
                .where(Agent.id == agent_id)
                .where(Agent.workspace_id == workspace_id)
                .where(Agent.user_id.is_(None))  # Not accepted yet
            )
            agent = result.scalar_one_or_none()
            if not agent:
                raise AgentManagementError("Agent invitation not found or already accepted")
            
            # Generate new token and extend expiration
            agent.invitation_token = generate_invitation_token()
            agent.invitation_expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            
            await self.db.commit()
            await self.db.refresh(agent)
            
            return agent
            
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, AgentManagementError):
                raise
            raise AgentManagementError(f"Failed to resend invitation: {str(e)}")
    
    async def get_agent_statistics(self, workspace_id: str) -> Dict[str, Any]:
        """
        Get agent statistics for workspace
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            Agent statistics
        """
        from sqlalchemy import func
        
        # Get agent counts
        from sqlalchemy import Integer
        
        result = await self.db.execute(
            select(
                func.count(Agent.id).label('total'),
                func.sum(func.cast(Agent.is_active, Integer)).label('active'),
                func.sum(func.cast(Agent.user_id.is_(None), Integer)).label('pending')
            )
            .where(Agent.workspace_id == workspace_id)
        )
        
        row = result.first()
        total = row.total or 0
        active = row.active or 0
        pending = row.pending or 0
        inactive = total - active - pending
        
        # Get tier information
        tier_info = await self.tier_manager.get_workspace_tier_info(workspace_id)
        
        return {
            "total_agents": total,
            "active_agents": active,
            "inactive_agents": inactive,
            "pending_invitations": pending,
            "tier_info": {
                "current_tier": tier_info["tier"],
                "agent_limit": tier_info["limits"]["agents"],
                "agents_remaining": tier_info["remaining"]["agents"]
            }
        }


# ─── Convenience Functions ────────────────────────────────────────────────────

async def invite_agent(
    db: AsyncSession,
    workspace_id: str,
    email: str,
    name: str,
    invited_by_user_id: str
) -> Agent:
    """
    Convenience function to invite an agent
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        email: Agent email
        name: Agent name
        invited_by_user_id: User ID who sent invitation
    
    Returns:
        Created Agent instance
    
    Raises:
        AgentManagementError: If invitation fails
        TierLimitError: If agent limit exceeded
    """
    manager = AgentManager(db)
    return await manager.create_agent_invitation(workspace_id, email, name, invited_by_user_id)


async def accept_invitation(
    db: AsyncSession,
    invitation_token: str,
    user_id: str
) -> Agent:
    """
    Convenience function to accept agent invitation
    
    Args:
        db: Database session
        invitation_token: Invitation token
        user_id: User ID accepting invitation
    
    Returns:
        Updated Agent instance
    
    Raises:
        AgentManagementError: If acceptance fails
    """
    manager = AgentManager(db)
    return await manager.accept_agent_invitation(invitation_token, user_id)


async def get_workspace_agent_list(
    db: AsyncSession,
    workspace_id: str,
    include_inactive: bool = False
) -> List[Agent]:
    """
    Get agents for a workspace
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        include_inactive: Include inactive agents
    
    Returns:
        List of agents
    """
    manager = AgentManager(db)
    return await manager.get_workspace_agents(workspace_id, include_inactive)