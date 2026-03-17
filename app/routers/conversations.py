"""
Conversation Management Router
Handles conversation listing, management, and agent assignment with authentication
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from datetime import datetime

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, get_current_agent
from app.models.user import User
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.conversation_manager import ConversationManager, ConversationManagementError
from app.services.websocket_events import notify_agent_claim, notify_conversation_status_change


router = APIRouter(prefix="/api/conversations", tags=["conversations"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Response model for message information"""
    id: str
    content: str
    role: str  # customer, assistant, agent
    sender_name: Optional[str] = None
    created_at: str
    metadata: Optional[dict] = None


class ContactResponse(BaseModel):
    """Response model for contact information"""
    id: str
    name: str
    external_id: str
    channel_type: str
    metadata: Optional[dict] = None


class ConversationResponse(BaseModel):
    """Response model for conversation information"""
    id: str
    status: str  # active, escalated, agent, resolved
    contact: ContactResponse
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    escalation_reason: Optional[str] = None
    message_count: int
    last_message: Optional[MessageResponse] = None
    created_at: str
    updated_at: str


class ConversationDetailResponse(BaseModel):
    """Response model for detailed conversation information"""
    id: str
    status: str
    contact: ContactResponse
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    escalation_reason: Optional[str] = None
    messages: List[MessageResponse]
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    """Response model for conversation list"""
    conversations: List[ConversationResponse]
    total_count: int
    has_more: bool


class ConversationStatsResponse(BaseModel):
    """Response model for conversation statistics"""
    total_conversations: int
    active_conversations: int
    escalated_conversations: int
    agent_conversations: int
    resolved_conversations: int
    my_conversations: Optional[int] = None  # For agents


class ConversationClaimRequest(BaseModel):
    """Request model for claiming a conversation"""
    conversation_id: str = Field(..., description="Conversation ID to claim")


class ConversationStatusUpdateRequest(BaseModel):
    """Request model for updating conversation status"""
    conversation_id: str = Field(..., description="Conversation ID")
    status: str = Field(..., description="New status (active, escalated, agent, resolved)")
    note: Optional[str] = Field(None, description="Optional note for status change")


class AgentMessageRequest(BaseModel):
    """Request model for sending agent messages"""
    content: str = Field(..., min_length=1, max_length=2000, description="Message content")


# ─── Conversation Management Endpoints ────────────────────────────────────────

@router.get("/", response_model=ConversationListResponse)
async def list_conversations(
    status: Optional[str] = Query(None, description="Filter by status"),
    assigned_to_me: bool = Query(False, description="Show only conversations assigned to current user (agents only)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of conversations to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    List conversations for the workspace
    
    Args:
        status: Filter by conversation status
        assigned_to_me: Show only conversations assigned to current user (for agents)
        limit: Maximum number of conversations to return
        offset: Offset for pagination
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of conversations with pagination info
    """
    try:
        manager = ConversationManager(db)
        
        # Determine if user is an agent
        agent_id = None
        if assigned_to_me:
            from sqlalchemy import select
            result = await db.execute(
                select(Agent).where(
                    Agent.user_id == current_user.id,
                    Agent.workspace_id == current_workspace.id,
                    Agent.is_active == True
                )
            )
            agent = result.scalar_one_or_none()
            if agent:
                agent_id = agent.id
        
        conversations_data = await manager.get_workspace_conversations(
            workspace_id=current_workspace.id,
            status_filter=status,
            assigned_agent_id=agent_id,
            limit=limit,
            offset=offset
        )
        
        return ConversationListResponse(
            conversations=[ConversationResponse(**conv) for conv in conversations_data["conversations"]],
            total_count=conversations_data["total_count"],
            has_more=conversations_data["has_more"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list conversations: {str(e)}"
        )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed conversation information with messages
    
    Args:
        conversation_id: Conversation ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Detailed conversation information
    
    Raises:
        HTTPException: If conversation not found
    """
    try:
        manager = ConversationManager(db)
        conversation_data = await manager.get_conversation_detail(
            conversation_id=conversation_id,
            workspace_id=current_workspace.id
        )
        
        if not conversation_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        return ConversationDetailResponse(**conversation_data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversation: {str(e)}"
        )


@router.post("/claim", response_model=dict)
async def claim_conversation(
    request: ConversationClaimRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Claim an escalated conversation (agents only)
    
    Args:
        request: Conversation claim request
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If not authorized or conversation cannot be claimed
    """
    try:
        # Verify user is an active agent
        from sqlalchemy import select
        result = await db.execute(
            select(Agent).where(
                Agent.user_id == current_user.id,
                Agent.workspace_id == current_workspace.id,
                Agent.is_active == True
            )
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only active agents can claim conversations"
            )
        
        # Claim conversation
        manager = ConversationManager(db)
        await manager.claim_conversation(
            conversation_id=request.conversation_id,
            agent_id=agent.id,
            workspace_id=current_workspace.id
        )
        
        # Send WebSocket notification
        await notify_agent_claim(
            db=db,
            workspace_id=str(current_workspace.id),
            conversation_id=request.conversation_id,
            agent_id=str(agent.id),
            agent_name=agent.name
        )
        
        return {"message": "Conversation claimed successfully"}
        
    except ConversationManagementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to claim conversation: {str(e)}"
        )


@router.post("/status", response_model=dict)
async def update_conversation_status(
    request: ConversationStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Update conversation status
    
    Args:
        request: Status update request
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If not authorized or invalid status transition
    """
    try:
        manager = ConversationManager(db)
        
        # Get current conversation status before updating
        from sqlalchemy import select
        result = await db.execute(
            select(Conversation.status)
            .where(Conversation.id == request.conversation_id)
            .where(Conversation.workspace_id == current_workspace.id)
        )
        old_status = result.scalar_one_or_none()
        
        if not old_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Check if user has permission to update this conversation
        # Workspace owners can update any conversation
        # Agents can only update conversations assigned to them
        agent_id = None
        result = await db.execute(
            select(Agent).where(
                Agent.user_id == current_user.id,
                Agent.workspace_id == current_workspace.id,
                Agent.is_active == True
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            agent_id = agent.id
        
        await manager.update_conversation_status(
            conversation_id=request.conversation_id,
            new_status=request.status,
            workspace_id=current_workspace.id,
            user_id=current_user.id,
            agent_id=agent_id,
            note=request.note
        )
        
        # Send WebSocket notification
        from app.services.websocket_events import notify_conversation_status_change
        await notify_conversation_status_change(
            db=db,
            workspace_id=str(current_workspace.id),
            conversation_id=request.conversation_id,
            old_status=old_status,
            new_status=request.status,
            agent_id=str(agent_id) if agent_id else None
        )
        
        return {"message": f"Conversation status updated to {request.status}"}
        
    except ConversationManagementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update conversation status: {str(e)}"
        )


@router.post("/{conversation_id}/messages", response_model=dict)
async def send_agent_message(
    conversation_id: str,
    request: AgentMessageRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message as an agent in a conversation
    
    Args:
        conversation_id: Conversation ID
        request: Message request with content
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message with message ID
    
    Raises:
        HTTPException: If not authorized or conversation not found
    """
    try:
        # Verify user is an active agent
        from sqlalchemy import select
        result = await db.execute(
            select(Agent).where(
                Agent.user_id == current_user.id,
                Agent.workspace_id == current_workspace.id,
                Agent.is_active == True
            )
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only active agents can send messages"
            )
        
        # Send message
        manager = ConversationManager(db)
        message = await manager.send_agent_message(
            conversation_id=conversation_id,
            agent_id=agent.id,
            content=request.content,
            workspace_id=current_workspace.id
        )
        
        # Send WebSocket notification
        from app.services.websocket_events import notify_new_message
        await notify_new_message(
            db=db,
            workspace_id=str(current_workspace.id),
            conversation_id=conversation_id,
            message_id=str(message.id)
        )
        
        return {
            "message": "Message sent successfully",
            "message_id": str(message.id)
        }
        
    except ConversationManagementError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {str(e)}"
        )


@router.get("/stats/summary", response_model=ConversationStatsResponse)
async def get_conversation_statistics(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get conversation statistics for the workspace
    
    Args:
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Conversation statistics
    """
    try:
        from sqlalchemy import select, func
        
        # Get conversation counts by status
        result = await db.execute(
            select(
                Conversation.status,
                func.count(Conversation.id).label('count')
            )
            .where(Conversation.workspace_id == current_workspace.id)
            .group_by(Conversation.status)
        )
        
        stats = {
            "total_conversations": 0,
            "active_conversations": 0,
            "escalated_conversations": 0,
            "agent_conversations": 0,
            "resolved_conversations": 0
        }
        
        for row in result:
            status_name = row.status
            count = row.count
            stats["total_conversations"] += count
            
            if status_name == "active":
                stats["active_conversations"] += count
            elif status_name == "escalated":
                stats["escalated_conversations"] += count
            elif status_name == "agent":
                stats["agent_conversations"] += count
            elif status_name == "resolved":
                stats["resolved_conversations"] += count
        
        # If user is an agent, get their conversation count
        my_conversations = None
        from sqlalchemy import select
        result = await db.execute(
            select(Agent).where(
                Agent.user_id == current_user.id,
                Agent.workspace_id == current_workspace.id,
                Agent.is_active == True
            )
        )
        agent = result.scalar_one_or_none()
        
        if agent:
            my_result = await db.execute(
                select(func.count(Conversation.id))
                .where(Conversation.workspace_id == current_workspace.id)
                .where(Conversation.assigned_agent_id == agent.id)
                .where(Conversation.status.in_(["agent", "escalated"]))
            )
            my_conversations = my_result.scalar()
        
        return ConversationStatsResponse(
            total_conversations=stats["total_conversations"],
            active_conversations=stats["active_conversations"],
            escalated_conversations=stats["escalated_conversations"],
            agent_conversations=stats["agent_conversations"],
            resolved_conversations=stats["resolved_conversations"],
            my_conversations=my_conversations
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversation statistics: {str(e)}"
        )


# ─── Agent-Specific Endpoints ─────────────────────────────────────────────────

@router.get("/my/active", response_model=ConversationListResponse)
async def get_my_active_conversations(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of conversations to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get active conversations assigned to the current agent
    
    Args:
        limit: Maximum number of conversations to return
        offset: Offset for pagination
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of conversations assigned to current agent
    
    Raises:
        HTTPException: If user is not an active agent
    """
    try:
        # Verify user is an active agent
        from sqlalchemy import select
        result = await db.execute(
            select(Agent).where(
                Agent.user_id == current_user.id,
                Agent.workspace_id == current_workspace.id,
                Agent.is_active == True
            )
        )
        agent = result.scalar_one_or_none()
        
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only active agents can access this endpoint"
            )
        
        # Get agent's conversations
        manager = ConversationManager(db)
        conversations_data = await manager.get_workspace_conversations(
            workspace_id=current_workspace.id,
            status_filter=None,
            assigned_agent_id=agent.id,
            limit=limit,
            offset=offset
        )
        
        return ConversationListResponse(
            conversations=[ConversationResponse(**conv) for conv in conversations_data["conversations"]],
            total_count=conversations_data["total_count"],
            has_more=conversations_data["has_more"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent conversations: {str(e)}"
        )