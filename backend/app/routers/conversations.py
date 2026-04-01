"""
Conversation Management Router
Handles conversation listing, management, and agent assignment with authentication
"""
from typing import List, Optional, AsyncGenerator
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, text, null
from pydantic import BaseModel, Field
from datetime import datetime, date
import csv
import io

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
    status_filter: Optional[str] = Query(None, description="Filter by status"),
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
        status_filter: Filter by conversation status
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
        
        conversations = await manager.get_workspace_conversations(
            workspace_id=current_workspace.id,
            status=status_filter,
            limit=limit,
            offset=offset
        )
        
        # Filter by agent if requested
        if assigned_to_me and agent_id:
            conversations = [c for c in conversations if c.assigned_agent_id == agent_id]
        
        # Convert to response format
        conversation_responses = []
        for conv in conversations:
            # Get last message and count via queries (avoid lazy-loading in async)
            from sqlalchemy import select, func
            from app.models.message import Message
            last_msg_result = await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_msg_row = last_msg_result.scalar_one_or_none()
            last_message = None
            if last_msg_row:
                last_message = MessageResponse(
                    id=str(last_msg_row.id),
                    content=last_msg_row.content,
                    role=last_msg_row.role,
                    sender_name=None,
                    created_at=last_msg_row.created_at.isoformat(),
                    metadata=last_msg_row.extra_data
                )

            msg_count_result = await db.execute(
                select(func.count(Message.id)).where(Message.conversation_id == conv.id)
            )
            message_count = msg_count_result.scalar() or 0
            
            conversation_responses.append(ConversationResponse(
                id=str(conv.id),
                status=conv.status,
                contact=ContactResponse(
                    id=str(conv.contact.id),
                    name=conv.contact.name,
                    external_id=conv.contact.external_id,
                    channel_type=conv.contact.channel_type if hasattr(conv.contact, 'channel_type') else "unknown",
                    metadata=conv.contact.meta
                ),
                assigned_agent_id=str(conv.assigned_agent_id) if conv.assigned_agent_id else None,
                assigned_agent_name=conv.assigned_agent.name if conv.assigned_agent else None,
                escalation_reason=conv.escalation_reason,
                message_count=message_count,
                last_message=last_message,
                created_at=conv.created_at.isoformat(),
                updated_at=conv.updated_at.isoformat()
            ))
        
        return ConversationListResponse(
            conversations=conversation_responses,
            total_count=len(conversation_responses),
            has_more=len(conversations) == limit
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list conversations: {str(e)}"
        )


# ─── Search & Export ─────────────────────────────────────────────────────────
# IMPORTANT: These must be declared BEFORE /{conversation_id} to avoid FastAPI
# treating "search" and "export" as conversation ID path params.

class ConversationSearchResult(BaseModel):
    id: str
    status: str
    channel_type: str
    contact_name: Optional[str]
    created_at: str
    updated_at: str
    message_snippet: Optional[str]


class ConversationSearchResponse(BaseModel):
    results: List[ConversationSearchResult]
    total_count: int
    has_more: bool


@router.get("/search", response_model=ConversationSearchResponse)
async def search_conversations(
    q: Optional[str] = Query(None, description="Full-text search across message content"),
    contact_name: Optional[str] = Query(None),
    channel_type_filter: Optional[str] = Query(None, alias="channel_type"),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    assigned_agent_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Search conversations by message content and filters."""
    from sqlalchemy import select
    from app.models.contact import Contact as ContactModel
    from app.models.message import Message as MessageModel

    base_filters = [Conversation.workspace_id == current_workspace.id]

    if channel_type_filter:
        base_filters.append(Conversation.channel_type == channel_type_filter)
    if status_filter:
        base_filters.append(Conversation.status == status_filter)
    if date_from:
        base_filters.append(Conversation.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        base_filters.append(Conversation.created_at <= datetime.combine(date_to, datetime.max.time()))
    if assigned_agent_id:
        base_filters.append(Conversation.assigned_agent_id == UUID(assigned_agent_id))

    if q:
        # Full-text search: join messages, filter by tsvector match
        ts_query = func.plainto_tsquery("english", q)
        ts_vector = func.to_tsvector("english", MessageModel.content)
        headline = func.ts_headline(
            "english",
            MessageModel.content,
            ts_query,
            "MaxWords=20, MinWords=8, ShortWord=3",
        ).label("snippet")

        query = (
            select(
                Conversation,
                func.min(headline).label("snippet"),
            )
            .join(MessageModel, MessageModel.conversation_id == Conversation.id)
            .join(ContactModel, ContactModel.id == Conversation.contact_id)
            .where(*base_filters)
            .where(ts_vector.op("@@")(ts_query))
        )
        if contact_name:
            query = query.where(ContactModel.name.ilike(f"%{contact_name}%"))
        query = query.group_by(Conversation.id)
    else:
        query = (
            select(Conversation, null().label("snippet"))
            .join(ContactModel, ContactModel.id == Conversation.contact_id)
            .where(*base_filters)
        )
        if contact_name:
            query = query.where(ContactModel.name.ilike(f"%{contact_name}%"))

    count_sq = query.subquery()
    total_count_result = await db.execute(select(func.count()).select_from(count_sq))
    total_count = total_count_result.scalar() or 0

    query = query.order_by(Conversation.updated_at.desc()).limit(limit + 1).offset(offset)
    rows = (await db.execute(query)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    # Load contact names
    conv_ids = [r[0].id for r in rows]
    contact_map: dict = {}
    if conv_ids:
        contact_results = await db.execute(
            select(Conversation.id, ContactModel.name)
            .join(ContactModel, ContactModel.id == Conversation.contact_id)
            .where(Conversation.id.in_(conv_ids))
        )
        contact_map = {str(cid): name for cid, name in contact_results.all()}

    return ConversationSearchResponse(
        results=[
            ConversationSearchResult(
                id=str(row[0].id),
                status=row[0].status,
                channel_type=row[0].channel_type,
                contact_name=contact_map.get(str(row[0].id)),
                created_at=row[0].created_at.isoformat(),
                updated_at=row[0].updated_at.isoformat(),
                message_snippet=row[1] if row[1] != "NULL" else None,
            )
            for row in rows
        ],
        total_count=total_count,
        has_more=has_more,
    )


@router.get("/export")
async def export_conversations_csv(
    q: Optional[str] = Query(None),
    contact_name_filter: Optional[str] = Query(None, alias="contact_name"),
    channel_type_filter: Optional[str] = Query(None, alias="channel_type"),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    assigned_agent_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """
    Export conversations as CSV (Growth+ tier).
    Streams rows to avoid memory issues on large datasets.
    """
    from app.config import TIER_LIMITS
    from app.models.contact import Contact as ContactModel
    from app.models.message import Message as MessageModel
    from app.models.agent import Agent as AgentModel
    from app.models.csat_rating import CSATRating

    if not TIER_LIMITS.get(current_workspace.tier or "free", {}).get("has_api_access", False):
        raise HTTPException(status_code=403, detail="CSV export requires Growth or Pro tier.")

    base_filters = [Conversation.workspace_id == current_workspace.id]
    if channel_type_filter:
        base_filters.append(Conversation.channel_type == channel_type_filter)
    if status_filter:
        base_filters.append(Conversation.status == status_filter)
    if date_from:
        base_filters.append(Conversation.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        base_filters.append(Conversation.created_at <= datetime.combine(date_to, datetime.max.time()))
    if assigned_agent_id:
        base_filters.append(Conversation.assigned_agent_id == UUID(assigned_agent_id))

    query = (
        select(
            Conversation,
            ContactModel.name.label("contact_name"),
            AgentModel.name.label("agent_name"),
            CSATRating.rating.label("csat_rating"),
            func.count(MessageModel.id).label("message_count"),
        )
        .join(ContactModel, ContactModel.id == Conversation.contact_id)
        .outerjoin(AgentModel, AgentModel.id == Conversation.assigned_agent_id)
        .outerjoin(CSATRating, CSATRating.conversation_id == Conversation.id)
        .outerjoin(MessageModel, MessageModel.conversation_id == Conversation.id)
        .where(*base_filters)
        .group_by(Conversation.id, ContactModel.name, AgentModel.name, CSATRating.rating)
        .order_by(Conversation.created_at.desc())
    )

    if contact_name_filter:
        query = query.where(ContactModel.name.ilike(f"%{contact_name_filter}%"))

    if q:
        ts_q = func.plainto_tsquery("english", q)
        query = query.where(
            Conversation.id.in_(
                select(MessageModel.conversation_id)
                .where(func.to_tsvector("english", MessageModel.content).op("@@")(ts_q))
            )
        )

    rows = (await db.execute(query)).all()

    async def generate_csv():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "conversation_id", "contact_name", "channel_type", "status",
            "created_at", "resolved_at", "message_count", "escalated",
            "assigned_agent_name", "csat_rating",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)

        for row in rows:
            conv = row[0]
            writer.writerow([
                str(conv.id),
                row.contact_name or "",
                conv.channel_type,
                conv.status,
                conv.created_at.isoformat(),
                conv.resolved_at.isoformat() if conv.resolved_at else "",
                row.message_count or 0,
                "yes" if conv.escalation_reason else "no",
                row.agent_name or "",
                row.csat_rating or "",
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=conversations.csv"},
    )


@router.get("/{conversation_id}/csat", response_model=Optional[dict])
async def get_conversation_csat(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Get the CSAT rating for a conversation, if submitted."""
    from sqlalchemy import select
    from app.models.csat_rating import CSATRating

    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .where(Conversation.workspace_id == current_workspace.id)
    )
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        select(CSATRating).where(CSATRating.conversation_id == UUID(conversation_id))
    )
    rating = result.scalar_one_or_none()
    if not rating:
        return None
    return {
        "id": str(rating.id),
        "conversation_id": str(rating.conversation_id),
        "rating": rating.rating,
        "comment": rating.comment,
        "submitted_at": rating.submitted_at.isoformat(),
    }


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
            agent_id=agent_id,
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

        # Fire outbound webhook for resolved conversations (fire-and-forget)
        if request.status == "resolved":
            try:
                import asyncio
                from app.services.outbound_webhook_service import trigger_event
                asyncio.create_task(trigger_event(
                    db=db,
                    workspace_id=str(current_workspace.id),
                    event_type="conversation.resolved",
                    payload={
                        "workspace_id": str(current_workspace.id),
                        "conversation_id": request.conversation_id,
                        "resolved_by": str(current_user.id),
                        "note": request.note,
                    }
                ))
            except Exception:
                pass

            # Send CSAT prompt for webchat conversations (fire-and-forget)
            try:
                conv_result = await db.execute(
                    select(Conversation)
                    .where(Conversation.id == UUID(request.conversation_id))
                    .where(Conversation.workspace_id == current_workspace.id)
                )
                resolved_conv = conv_result.scalar_one_or_none()
                if resolved_conv and resolved_conv.channel_type == "webchat":
                    import asyncio
                    from app.services.csat_service import generate_and_send_csat_prompt
                    asyncio.create_task(generate_and_send_csat_prompt(
                        db=db,
                        conversation_id=request.conversation_id,
                        workspace_id=str(current_workspace.id),
                    ))
            except Exception:
                pass

        # Push status change to customer WS for relevant transitions
        if request.status in ("escalated", "agent", "resolved"):
            try:
                from app.models.contact import Contact
                from app.services.websocket_events import notify_customer_status_change
                sc_result = await db.execute(
                    select(Conversation, Contact)
                    .join(Contact, Contact.id == Conversation.contact_id)
                    .where(Conversation.id == UUID(request.conversation_id))
                    .where(Conversation.workspace_id == current_workspace.id)
                )
                sc_row = sc_result.first()
                if sc_row and sc_row[0].channel_type == "webchat":
                    await notify_customer_status_change(
                        workspace_id=str(current_workspace.id),
                        session_token=sc_row[1].external_id,
                        new_status=request.status,
                    )
            except Exception:
                pass

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
        from sqlalchemy import select
        manager = ConversationManager(db)

        # Workspace owners can always send messages
        is_owner = str(current_workspace.owner_id) == str(current_user.id)

        if is_owner:
            message = await manager.send_owner_message(
                conversation_id=conversation_id,
                owner_user_id=str(current_user.id),
                content=request.content,
                workspace_id=str(current_workspace.id)
            )
        else:
            # Verify user is an active agent
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

            message = await manager.send_agent_message(
                conversation_id=conversation_id,
                agent_id=agent.id,
                content=request.content,
                workspace_id=str(current_workspace.id)
            )
        
        # Send WebSocket notification to agents
        from app.services.websocket_events import notify_new_message
        await notify_new_message(
            db=db,
            workspace_id=str(current_workspace.id),
            conversation_id=conversation_id,
            message_id=str(message.id)
        )

        # Push to customer WS if this is a webchat conversation
        try:
            from sqlalchemy import select
            from app.models.conversation import Conversation
            from app.models.contact import Contact
            from app.services.websocket_events import notify_customer_new_message
            conv_row = await db.execute(
                select(Conversation, Contact)
                .join(Contact, Contact.id == Conversation.contact_id)
                .where(Conversation.id == message.conversation_id)
            )
            row = conv_row.first()
            if row and row[0].channel_type == "webchat":
                await notify_customer_new_message(
                    db=db,
                    workspace_id=str(current_workspace.id),
                    session_token=row[1].external_id,
                    message_id=str(message.id),
                )
        except Exception:
            pass  # never block the agent reply

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


# ─── Internal Notes ────────────────────────────────────────────────────────────

class InternalNoteCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class InternalNoteResponse(BaseModel):
    id: str
    conversation_id: str
    agent_id: Optional[str]
    content: str
    created_at: str


@router.post("/{conversation_id}/notes", response_model=InternalNoteResponse)
async def create_internal_note(
    conversation_id: str,
    request: InternalNoteCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create an internal agent note on a conversation (not visible to customers)."""
    from sqlalchemy import select
    from app.models.conversation import Conversation
    from app.models.internal_note import InternalNote
    from app.models.agent import Agent

    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .where(Conversation.workspace_id == current_workspace.id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Resolve agent_id if user is an agent
    agent_result = await db.execute(
        select(Agent)
        .where(Agent.workspace_id == current_workspace.id)
        .where(Agent.user_id == current_user.id)
        .where(Agent.is_active == True)
    )
    agent = agent_result.scalar_one_or_none()

    note = InternalNote(
        conversation_id=UUID(conversation_id),
        agent_id=agent.id if agent else None,
        content=request.content
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    return InternalNoteResponse(
        id=str(note.id),
        conversation_id=str(note.conversation_id),
        agent_id=str(note.agent_id) if note.agent_id else None,
        content=note.content,
        created_at=note.created_at.isoformat()
    )


@router.get("/{conversation_id}/notes", response_model=List[InternalNoteResponse])
async def list_internal_notes(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """List internal notes for a conversation (agent/owner only)."""
    from sqlalchemy import select
    from app.models.conversation import Conversation
    from app.models.internal_note import InternalNote

    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .where(Conversation.workspace_id == current_workspace.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")

    notes_result = await db.execute(
        select(InternalNote)
        .where(InternalNote.conversation_id == UUID(conversation_id))
        .order_by(InternalNote.created_at.asc())
    )
    notes = notes_result.scalars().all()

    return [
        InternalNoteResponse(
            id=str(n.id),
            conversation_id=str(n.conversation_id),
            agent_id=str(n.agent_id) if n.agent_id else None,
            content=n.content,
            created_at=n.created_at.isoformat()
        )
        for n in notes
    ]


# ─── AI Response Feedback ──────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    rating: str = Field(..., pattern="^(positive|negative)$")
    comment: Optional[str] = Field(None, max_length=1000)


class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    rating: str
    comment: Optional[str]
    created_at: str


@router.post("/{conversation_id}/messages/{message_id}/feedback", response_model=FeedbackResponse)
async def submit_ai_feedback(
    conversation_id: str,
    message_id: str,
    request: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Submit thumbs-up/down feedback on an AI-generated message."""
    from sqlalchemy import select
    from app.models.message import Message
    from app.models.conversation import Conversation
    from app.models.ai_feedback import AIFeedback
    from app.models.agent import Agent

    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .where(Conversation.workspace_id == current_workspace.id)
    )
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_result = await db.execute(
        select(Message)
        .where(Message.id == UUID(message_id))
        .where(Message.conversation_id == UUID(conversation_id))
    )
    message = msg_result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # Check for existing feedback
    existing = await db.execute(
        select(AIFeedback).where(AIFeedback.message_id == UUID(message_id))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Feedback already submitted for this message")

    agent_result = await db.execute(
        select(Agent)
        .where(Agent.workspace_id == current_workspace.id)
        .where(Agent.user_id == current_user.id)
    )
    agent = agent_result.scalar_one_or_none()

    feedback = AIFeedback(
        message_id=UUID(message_id),
        workspace_id=current_workspace.id,
        agent_id=agent.id if agent else None,
        rating=request.rating,
        comment=request.comment
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(
        id=str(feedback.id),
        message_id=str(feedback.message_id),
        rating=feedback.rating,
        comment=feedback.comment,
        created_at=feedback.created_at.isoformat()
    )


@router.get("/{conversation_id}/messages/{message_id}/feedback", response_model=Optional[FeedbackResponse])
async def get_ai_feedback(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Get feedback for a specific message."""
    from sqlalchemy import select
    from app.models.ai_feedback import AIFeedback

    feedback_result = await db.execute(
        select(AIFeedback).where(AIFeedback.message_id == UUID(message_id))
    )
    feedback = feedback_result.scalar_one_or_none()
    if not feedback:
        return None

    return FeedbackResponse(
        id=str(feedback.id),
        message_id=str(feedback.message_id),
        rating=feedback.rating,
        comment=feedback.comment,
        created_at=feedback.created_at.isoformat()
    )