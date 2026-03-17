"""
Agent Management Router
Handles agent invitations, acceptance, and management endpoints
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
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
    deactivated_at: Optional[str] = None


class AgentInvitationResponse(BaseModel):
    """Response model for agent invitation"""
    id: str
    email: str
    name: str
    invitation_token: str
    invitation_expires_at: str
    invited_at: str


class AgentStatsResponse(BaseModel):
    """Response model for agent statistics"""
    total_agents: int
    active_agents: int
    inactive_agents: int
    pending_invitations: int
    tier_info: dict


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
            id=agent.id,
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
            id=agent.id,
            email=agent.email,
            name=agent.name,
            is_active=agent.is_active,
            user_id=agent.user_id,
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


@router.get("/", response_model=List[AgentResponse])
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
                id=agent.id,
                email=agent.email,
                name=agent.name,
                is_active=agent.is_active,
                user_id=agent.user_id,
                invited_at=agent.created_at.isoformat(),
                accepted_at=agent.accepted_at.isoformat() if agent.accepted_at else None,
                deactivated_at=agent.deactivated_at.isoformat() if agent.deactivated_at else None
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
                id=agent.id,
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
            id=agent.id,
            email=agent.email,
            name=agent.name,
            is_active=agent.is_active,
            user_id=agent.user_id,
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
            id=agent.id,
            email=agent.email,
            name=agent.name,
            is_active=agent.is_active,
            user_id=agent.user_id,
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
            id=agent.id,
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
        manager = AgentManager(db)
        stats = await manager.get_agent_statistics(current_workspace.id)
        
        return AgentStatsResponse(**stats)
        
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