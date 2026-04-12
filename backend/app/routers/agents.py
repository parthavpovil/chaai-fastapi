"""
Agent Management Router
Handles agent invitations, acceptance, and management endpoints
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, get_workspace_from_token, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.services.agent_manager import AgentManager, AgentManagementError
from app.services.tier_manager import TierLimitError


router = APIRouter(prefix="/api/agents", tags=["agents"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class AgentInviteRequest(BaseModel):
    """Request model for agent invitation"""
    email: EmailStr = Field(..., description="Agent email address")
    name: str = Field(..., min_length=1, max_length=100, description="Agent name")


class AgentAcceptRequest(BaseModel):
    """Request model for accepting agent invitation"""
    invitation_token: str = Field(..., min_length=1, description="Invitation token")


class AgentResponse(BaseModel):
    """Response model for agent information"""
    id: str
    email: str
    name: str
    is_active: bool
    user_id: Optional[str] = None
    invited_at: str
    accepted_at: Optional[str] = None


class AgentInvitationResponse(BaseModel):
    """Response model for agent invitation"""
    id: str
    email: str
    name: str
    invitation_token: str
    invitation_expires_at: str
    invited_at: str


class AgentPerformanceItem(BaseModel):
    """Per-agent performance metrics"""
    agent_id: str
    name: str
    email: str
    status: str
    conversations_active: int
    conversations_resolved_30d: int
    avg_csat: Optional[float] = None


class AgentStatsResponse(BaseModel):
    """Response model for agent statistics"""
    total_agents: int
    active_agents: int
    inactive_agents: int
    pending_invitations: int
    tier_info: dict
    per_agent: List[AgentPerformanceItem] = []


# ─── Agent Management Endpoints ───────────────────────────────────────────────

@router.post("/invite", response_model=AgentInvitationResponse)
async def invite_agent(
    request: AgentInviteRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Invite an agent to the workspace
    
    Args:
        request: Agent invitation request
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Agent invitation details
    
    Raises:
        HTTPException: If invitation fails or tier limits exceeded
    """
    try:
        manager = AgentManager(db)
        agent = await manager.create_agent_invitation(
            workspace_id=current_workspace.id,
            email=request.email,
            name=request.name,
            invited_by_user_id=current_user.id
        )
        
        return AgentInvitationResponse(
            id=str(agent.id),
            email=agent.email,
            name=agent.name,
            invitation_token=agent.invitation_token,
            invitation_expires_at=agent.invitation_expires_at.isoformat(),
            invited_at=agent.created_at.isoformat()
        )

    except TierLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except AgentManagementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to invite agent: {str(e)}"
        )


@router.post("/accept", response_model=AgentResponse)
async def accept_agent_invitation(
    request: AgentAcceptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Accept agent invitation
    
    Args:
        request: Agent acceptance request
        current_user: Current authenticated user
        db: Database session
    
    Returns:
        Updated agent information
    
    Raises:
        HTTPException: If acceptance fails
    """
    try:
        manager = AgentManager(db)
        agent = await manager.accept_agent_invitation(
            invitation_token=request.invitation_token,
            user_id=current_user.id
        )
        
        # Send WebSocket notification about new agent joining
        from app.services.websocket_events import WebSocketEventBroadcaster
        broadcaster = WebSocketEventBroadcaster(db)
        await broadcaster.broadcast_agent_status_change(
            workspace_id=str(agent.workspace_id),
            agent_id=str(agent.id),
            is_active=True,
            status_reason="Agent accepted invitation and joined workspace"
        )
        
        return AgentResponse(
            id=str(agent.id),
            email=agent.email,
            name=agent.name,
            is_active=agent.is_active,
            user_id=str(agent.user_id) if agent.user_id else None,
            invited_at=agent.created_at.isoformat(),
            accepted_at=agent.accepted_at.isoformat() if agent.accepted_at else None,
            deactivated_at=agent.deactivated_at.isoformat() if agent.deactivated_at else None
        )

    except AgentManagementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to accept invitation: {str(e)}"
        )


@router.get("/", response_model=List[AgentResponse], dependencies=[Depends(require_permission("team.manage"))])
async def list_agents(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    List agents for the workspace
    
    Args:
        include_inactive: Whether to include inactive agents
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of agents
    """
    try:
        manager = AgentManager(db)
        agents = await manager.get_workspace_agents(
            workspace_id=current_workspace.id,
            include_inactive=include_inactive
        )
        
        agent_list = []
        for agent in agents:
            agent_list.append(AgentResponse(
                id=str(agent.id),
                email=agent.email,
                name=agent.name,
                is_active=agent.is_active,
                user_id=str(agent.user_id) if agent.user_id else None,
                invited_at=agent.created_at.isoformat(),
                accepted_at=agent.invitation_accepted_at.isoformat() if agent.invitation_accepted_at else None
            ))
        
        return agent_list
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents: {str(e)}"
        )


@router.get("/pending", response_model=List[AgentInvitationResponse])
async def list_pending_invitations(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    List pending agent invitations
    
    Args:
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of pending invitations
    """
    try:
        manager = AgentManager(db)
        pending_agents = await manager.get_pending_invitations(current_workspace.id)
        
        invitation_list = []
        for agent in pending_agents:
            invitation_list.append(AgentInvitationResponse(
                id=str(agent.id),
                email=agent.email,
                name=agent.name,
                invitation_token=agent.invitation_token,
                invitation_expires_at=agent.invitation_expires_at.isoformat(),
                invited_at=agent.created_at.isoformat()
            ))
        
        return invitation_list
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list pending invitations: {str(e)}"
        )


@router.post("/{agent_id}/deactivate", response_model=AgentResponse)
async def deactivate_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Deactivate an agent
    
    Args:
        agent_id: Agent ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Updated agent information
    
    Raises:
        HTTPException: If deactivation fails
    """
    try:
        manager = AgentManager(db)
        agent = await manager.deactivate_agent(
            agent_id=agent_id,
            workspace_id=current_workspace.id,
            deactivated_by_user_id=current_user.id
        )
        
        # Send WebSocket notification about agent status change
        from app.services.websocket_events import WebSocketEventBroadcaster
        broadcaster = WebSocketEventBroadcaster(db)
        await broadcaster.broadcast_agent_status_change(
            workspace_id=str(current_workspace.id),
            agent_id=str(agent.id),
            is_active=False,
            status_reason="Deactivated by workspace owner"
        )
        
        return AgentResponse(
            id=str(agent.id),
            email=agent.email,
            name=agent.name,
            is_active=agent.is_active,
            user_id=str(agent.user_id) if agent.user_id else None,
            invited_at=agent.created_at.isoformat(),
            accepted_at=agent.accepted_at.isoformat() if agent.accepted_at else None,
            deactivated_at=agent.deactivated_at.isoformat() if agent.deactivated_at else None
        )

    except AgentManagementError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate agent: {str(e)}"
        )


@router.post("/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Activate an agent (reactivate if previously deactivated)
    
    Args:
        agent_id: Agent ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Updated agent information
    
    Raises:
        HTTPException: If activation fails
    """
    try:
        from sqlalchemy import select
        
        # Get agent
        result = await db.execute(
            select(Agent)
            .where(Agent.id == agent_id)
            .where(Agent.workspace_id == current_workspace.id)
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )
        
        if not agent.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot activate agent that hasn't accepted invitation"
            )
        
        # Check tier limits before activation
        manager = AgentManager(db)
        await manager.tier_manager.check_agent_limit(current_workspace.id)
        
        # Activate agent
        agent.is_active = True
        agent.deactivated_at = None
        agent.deactivated_by = None
        
        await db.commit()
        await db.refresh(agent)
        
        # Send WebSocket notification about agent status change
        from app.services.websocket_events import WebSocketEventBroadcaster
        broadcaster = WebSocketEventBroadcaster(db)
        await broadcaster.broadcast_agent_status_change(
            workspace_id=str(current_workspace.id),
            agent_id=str(agent.id),
            is_active=True,
            status_reason="Activated by workspace owner"
        )
        
        return AgentResponse(
            id=str(agent.id),
            email=agent.email,
            name=agent.name,
            is_active=agent.is_active,
            user_id=str(agent.user_id) if agent.user_id else None,
            invited_at=agent.created_at.isoformat(),
            accepted_at=agent.accepted_at.isoformat() if agent.accepted_at else None,
            deactivated_at=agent.deactivated_at.isoformat() if agent.deactivated_at else None
        )

    except TierLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate agent: {str(e)}"
        )


@router.post("/{agent_id}/resend", response_model=AgentInvitationResponse)
async def resend_agent_invitation(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Resend agent invitation
    
    Args:
        agent_id: Agent ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Updated invitation details
    
    Raises:
        HTTPException: If resend fails
    """
    try:
        manager = AgentManager(db)
        agent = await manager.resend_agent_invitation(
            agent_id=agent_id,
            workspace_id=current_workspace.id,
            resent_by_user_id=current_user.id
        )
        
        return AgentInvitationResponse(
            id=str(agent.id),
            email=agent.email,
            name=agent.name,
            invitation_token=agent.invitation_token,
            invitation_expires_at=agent.invitation_expires_at.isoformat(),
            invited_at=agent.created_at.isoformat()
        )

    except AgentManagementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resend invitation: {str(e)}"
        )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an agent (only for pending invitations)
    
    Args:
        agent_id: Agent ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If deletion fails
    """
    try:
        from sqlalchemy import select
        
        # Get agent
        result = await db.execute(
            select(Agent)
            .where(Agent.id == agent_id)
            .where(Agent.workspace_id == current_workspace.id)
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )
        
        # Only allow deletion of pending invitations
        if agent.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete agent that has accepted invitation. Use deactivate instead."
            )
        
        await db.delete(agent)
        await db.commit()
        
        return {"message": "Agent invitation deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete agent: {str(e)}"
        )


# ─── Agent Statistics Endpoint ────────────────────────────────────────────────

@router.get("/stats", response_model=AgentStatsResponse)
async def get_agent_statistics(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get agent statistics for the workspace
    
    Args:
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Agent statistics
    """
    try:
        from app.models.conversation import Conversation
        from app.models.csat_rating import CSATRating

        manager = AgentManager(db)
        stats = await manager.get_agent_statistics(current_workspace.id)

        # Fetch all active agents for per-agent breakdown
        agents_result = await db.execute(
            select(Agent)
            .where(Agent.workspace_id == current_workspace.id)
            .where(Agent.is_active == True)
            .where(Agent.user_id != None)
        )
        agents = agents_result.scalars().all()

        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        per_agent = []

        for agent in agents:
            # Active conversations assigned to this agent
            active_result = await db.execute(
                select(func.count(Conversation.id))
                .where(Conversation.workspace_id == current_workspace.id)
                .where(Conversation.assigned_agent_id == agent.id)
                .where(Conversation.status.in_(["escalated", "agent"]))
            )
            conversations_active = active_result.scalar() or 0

            # Resolved conversations in last 30 days
            resolved_result = await db.execute(
                select(func.count(Conversation.id))
                .where(Conversation.workspace_id == current_workspace.id)
                .where(Conversation.assigned_agent_id == agent.id)
                .where(Conversation.status == "resolved")
                .where(Conversation.resolved_at >= thirty_days_ago)
            )
            conversations_resolved_30d = resolved_result.scalar() or 0

            # Average CSAT for conversations handled by this agent
            csat_result = await db.execute(
                select(func.avg(CSATRating.rating))
                .join(Conversation, Conversation.id == CSATRating.conversation_id)
                .where(Conversation.assigned_agent_id == agent.id)
                .where(CSATRating.workspace_id == current_workspace.id)
            )
            avg_csat_raw = csat_result.scalar()
            avg_csat = round(float(avg_csat_raw), 2) if avg_csat_raw is not None else None

            per_agent.append(AgentPerformanceItem(
                agent_id=str(agent.id),
                name=agent.name,
                email=agent.email,
                status=getattr(agent, "status", "offline"),
                conversations_active=conversations_active,
                conversations_resolved_30d=conversations_resolved_30d,
                avg_csat=avg_csat,
            ))

        return AgentStatsResponse(**stats, per_agent=per_agent)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent statistics: {str(e)}"
        )


# ─── Agent Invitation Validation Endpoint ────────────────────────────────────

@router.get("/invitation/{invitation_token}")
async def validate_invitation_token(
    invitation_token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate agent invitation token
    
    Args:
        invitation_token: Invitation token
        db: Database session
    
    Returns:
        Invitation details if valid
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        manager = AgentManager(db)
        agent = await manager.get_agent_by_token(invitation_token)
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid or expired invitation token"
            )
        
        return {
            "valid": True,
            "agent_email": agent.email,
            "agent_name": agent.name,
            "workspace_id": agent.workspace_id,
            "expires_at": agent.invitation_expires_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate invitation: {str(e)}"
        )


# ─── Agent Availability Status ────────────────────────────────────────────────

from sqlalchemy import select as _select
from datetime import datetime, timezone


class AgentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(online|offline|busy)$")


class AgentStatusResponse(BaseModel):
    agent_id: str
    status: str
    last_heartbeat_at: Optional[str]


@router.put("/me/status", response_model=AgentStatusResponse, dependencies=[Depends(require_permission("agent_self.presence"))])
async def update_agent_status(
    request: AgentStatusUpdate,
    current_workspace: Workspace = Depends(get_workspace_from_token),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update the calling agent's availability status and heartbeat."""
    from app.services.websocket_events import notify_agent_status_change

    agent_result = await db.execute(
        _select(Agent)
        .where(Agent.workspace_id == current_workspace.id)
        .where(Agent.user_id == current_user.id)
        .where(Agent.is_active == True)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Active agent profile not found")

    agent.status = request.status
    agent.last_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(agent)

    # Broadcast status change to workspace via WebSocket
    try:
        await notify_agent_status_change(
            db=db,
            workspace_id=str(current_workspace.id),
            agent_id=str(agent.id),
            status=request.status
        )
    except Exception:
        pass  # Non-fatal

    return AgentStatusResponse(
        agent_id=str(agent.id),
        status=agent.status,
        last_heartbeat_at=agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None
    )


@router.get("/me/status", response_model=AgentStatusResponse, dependencies=[Depends(require_permission("agent_self.presence"))])
async def get_agent_status(
    current_workspace: Workspace = Depends(get_workspace_from_token),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the calling agent's current availability status."""
    agent_result = await db.execute(
        _select(Agent)
        .where(Agent.workspace_id == current_workspace.id)
        .where(Agent.user_id == current_user.id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    return AgentStatusResponse(
        agent_id=str(agent.id),
        status=agent.status,
        last_heartbeat_at=agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None
    )