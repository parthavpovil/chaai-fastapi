"""
WebChat Public API Router
Public endpoints for website chat widget functionality
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.message_processor import MessageProcessor, process_incoming_message, MessageProcessingError
from app.services.escalation_router import check_and_escalate_message
from app.services.rag_engine import generate_rag_response
from app.services.usage_tracker import track_message_usage
from app.services.websocket_events import notify_new_message
from app.services.rate_limiter import check_webchat_rate_limit, RateLimitExceededError
from app.services.webhook_security import generate_session_token
from app.services.encryption import decrypt_credential


router = APIRouter(prefix="/api/webchat", tags=["WebChat"])


# ─── Request/Response Schemas ─────────────────────────────────────────────────

class WebChatSendRequest(BaseModel):
    """Request schema for sending WebChat messages"""
    widget_id: str = Field(..., description="Widget ID for the WebChat channel")
    session_token: Optional[str] = Field(None, description="Session token for message threading")
    message: str = Field(..., min_length=1, max_length=2000, description="Message content")
    contact_name: Optional[str] = Field(None, max_length=100, description="Contact display name")


class WebChatSendResponse(BaseModel):
    """Response schema for WebChat send endpoint"""
    success: bool
    session_token: str
    message_id: str
    response: Optional[str] = None
    error: Optional[str] = None


class WebChatMessage(BaseModel):
    """WebChat message schema"""
    id: str
    content: str
    sender_type: str  # "user" or "assistant"
    timestamp: datetime
    
    class Config:
        from_attributes = True


class WebChatMessagesResponse(BaseModel):
    """Response schema for WebChat messages endpoint"""
    messages: List[WebChatMessage]
    has_more: bool
    session_token: str


class WebChatConfigResponse(BaseModel):
    """Response schema for WebChat configuration endpoint"""
    widget_id: str
    business_name: str
    primary_color: str
    position: str
    welcome_message: str


# ─── Helper Functions ─────────────────────────────────────────────────────────

async def get_webchat_channel_by_widget_id(
    db: AsyncSession, 
    widget_id: str
) -> Optional[Channel]:
    """
    Get WebChat channel by widget_id and validate it's active
    
    Args:
        db: Database session
        widget_id: Widget ID to lookup
        
    Returns:
        Channel instance or None if not found/inactive
    """
    result = await db.execute(
        select(Channel)
        .where(Channel.type == "webchat")
        .where(Channel.is_active == True)
    )
    
    channels = result.scalars().all()
    
    # Check each channel's config for matching widget_id
    for channel in channels:
        if channel.config:
            try:
                # Decrypt and parse JSON config
                import json
                decrypted_config_str = decrypt_credential(channel.config)
                decrypted_config = json.loads(decrypted_config_str)
                if decrypted_config.get("widget_id") == widget_id:
                    return channel
            except Exception:
                # Skip channels with invalid config
                continue
    
    return None


async def get_webchat_conversation(
    db: AsyncSession,
    channel: Channel,
    session_token: str
) -> Optional[Conversation]:
    """
    Get existing WebChat conversation by session token
    
    Args:
        db: Database session
        channel: WebChat channel
        session_token: Session token
        
    Returns:
        Conversation instance or None
    """
    # Find contact with this session token
    result = await db.execute(
        select(Contact)
        .where(Contact.workspace_id == channel.workspace_id)
        .where(Contact.channel_id == channel.id)
        .where(Contact.external_contact_id == session_token)
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        return None
    
    # Find active conversation for this contact
    result = await db.execute(
        select(Conversation)
        .where(Conversation.workspace_id == channel.workspace_id)
        .where(Conversation.contact_id == contact.id)
        .where(Conversation.channel_id == channel.id)
        .where(Conversation.status.in_(["active", "escalated", "agent"]))
        .order_by(Conversation.updated_at.desc())
    )
    
    return result.scalar_one_or_none()


async def get_webchat_channel_by_workspace_slug(
    db: AsyncSession,
    workspace_slug: str
) -> Optional[tuple[Channel, Workspace]]:
    """
    Get WebChat channel and workspace by workspace slug
    
    Args:
        db: Database session
        workspace_slug: Workspace slug to lookup
        
    Returns:
        Tuple of (Channel, Workspace) or None if not found/inactive
    """
    # First get the workspace by slug
    result = await db.execute(
        select(Workspace)
        .where(Workspace.slug == workspace_slug)
    )
    workspace = result.scalar_one_or_none()
    
    if not workspace:
        return None
    
    # Get the WebChat channel for this workspace
    result = await db.execute(
        select(Channel)
        .where(Channel.workspace_id == workspace.id)
        .where(Channel.type == "webchat")
        .where(Channel.is_active == True)
    )
    channel = result.scalar_one_or_none()
    
    if not channel:
        return None
    
    return channel, workspace


# ─── WebChat Endpoints ────────────────────────────────────────────────────────

@router.get("/config/{workspace_slug}", response_model=WebChatConfigResponse)
async def get_webchat_config(
    workspace_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get WebChat widget configuration by workspace slug
    
    This endpoint allows website widgets to fetch their configuration based on
    the workspace slug. The widget will use this configuration to customize its
    appearance and behavior, and get the widget_id needed for sending messages.
    """
    try:
        # Get WebChat channel and workspace by slug
        result = await get_webchat_channel_by_workspace_slug(db, workspace_slug)
        if not result:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found or WebChat not configured"
            )
        
        channel, workspace = result
        
        # Decrypt and parse the channel configuration
        try:
            import json
            decrypted_config_str = decrypt_credential(channel.config)
            config = json.loads(decrypted_config_str)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to load WebChat configuration"
            )
        
        # Validate required configuration fields
        required_fields = ["widget_id", "business_name", "primary_color", "position", "welcome_message"]
        for field in required_fields:
            if field not in config:
                raise HTTPException(
                    status_code=500,
                    detail=f"WebChat configuration missing required field: {field}"
                )
        
        return WebChatConfigResponse(
            widget_id=config["widget_id"],
            business_name=config["business_name"],
            primary_color=config["primary_color"],
            position=config["position"],
            welcome_message=config["welcome_message"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/send", response_model=WebChatSendResponse)
async def send_webchat_message(
    request: WebChatSendRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message through WebChat widget without authentication
    
    This endpoint allows website visitors to send messages through the chat widget.
    It validates the widget_id, enforces rate limits, and processes the message
    through the AI pipeline.
    """
    try:
        # 1. Validate widget_id and get channel
        channel = await get_webchat_channel_by_widget_id(db, request.widget_id)
        if not channel:
            raise HTTPException(
                status_code=404,
                detail="Widget not found or inactive"
            )
        
        # 2. Generate or use existing session token
        session_token = request.session_token or generate_session_token()
        
        # 3. Check rate limits
        try:
            await check_webchat_rate_limit(
                db=db,
                session_token=session_token,
                workspace_id=str(channel.workspace_id)
            )
        except RateLimitExceededError as e:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "session_token": session_token,
                    "message_id": "",
                    "response": None,
                    "error": str(e)
                }
            )
        
        # 4. Process message through complete pipeline
        try:
            # Step 1: Process incoming message
            processing_result = await process_incoming_message(
                db=db,
                workspace_id=str(channel.workspace_id),
                channel_id=str(channel.id),
                external_contact_id=session_token,
                content=request.message,
                external_message_id=None,  # WebChat messages don't have external IDs
                contact_name=request.contact_name or f"WebChat User {session_token[:8]}",
                contact_data={"session_token": session_token},
                message_metadata={"session_token": session_token}
            )
            
            conversation_id = str(processing_result["conversation"].id)
            user_message_id = str(processing_result["message"].id)
            
            # Send WebSocket notification for customer message
            from app.services.websocket_events import notify_new_message
            await notify_new_message(
                db=db,
                workspace_id=str(channel.workspace_id),
                conversation_id=conversation_id,
                message_id=user_message_id
            )
            
            # Step 2: Check for escalation
            escalation_result = await check_and_escalate_message(
                db=db,
                conversation_id=conversation_id,
                workspace_id=str(channel.workspace_id),
                message_content=request.message
            )
            
            response_content = None
            
            if not escalation_result:
                # Step 3: Generate RAG response (only if not escalated)
                try:
                    rag_result = await generate_rag_response(
                        db=db,
                        workspace_id=str(channel.workspace_id),
                        query=request.message,
                        conversation_id=conversation_id,
                        max_tokens=300
                    )
                    
                    response_content = rag_result["response"]
                    input_tokens = rag_result["input_tokens"]
                    output_tokens = rag_result["output_tokens"]
                    
                    # Step 4: Create assistant response message
                    processor = MessageProcessor(db)
                    await processor.create_message(
                        conversation_id=conversation_id,
                        content=response_content,
                        role="assistant",
                        channel_type="webchat",
                        metadata={
                            "rag_used": True,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "webchat_response": True
                        }
                    )
                    
                    # Step 5: Track usage
                    await track_message_usage(
                        db=db,
                        workspace_id=str(channel.workspace_id),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens
                    )
                    
                    # Step 6: Send WebSocket notification
                    await notify_new_message(
                        db=db,
                        workspace_id=str(channel.workspace_id),
                        conversation_id=conversation_id,
                        message_id=user_message_id
                    )
                    
                except Exception as e:
                    print(f"RAG response generation failed: {e}")
                    # Use fallback response
                    response_content = "I'm sorry, I'm having trouble processing your request right now. Please try again later."
            else:
                # Message was escalated, provide escalation acknowledgment
                response_content = "Thank you for your message. I've escalated your request to our support team who will get back to you shortly."
            
        except MessageProcessingError as e:
            # Handle specific message processing errors
            if "maintenance" in str(e).lower():
                return WebChatSendResponse(
                    success=False,
                    session_token=session_token,
                    message_id="",
                    response=None,
                    error=str(e)
                )
            else:
                raise HTTPException(status_code=400, detail=str(e))
        
        except Exception as e:
            print(f"WebChat message processing failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to process message")
        
        return WebChatSendResponse(
            success=True,
            session_token=session_token,
            message_id=user_message_id,
            response=response_content,
            error=None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/messages", response_model=WebChatMessagesResponse)
async def get_webchat_messages(
    widget_id: str = Query(..., description="Widget ID for the WebChat channel"),
    session_token: str = Query(..., description="Session token for message threading"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of messages to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get messages for a WebChat session without authentication
    
    This endpoint allows website visitors to poll for new messages in their
    chat session. It validates the widget_id and session_token before returning
    messages.
    """
    try:
        # 1. Validate widget_id and get channel
        channel = await get_webchat_channel_by_widget_id(db, widget_id)
        if not channel:
            raise HTTPException(
                status_code=404,
                detail="Widget not found or inactive"
            )
        
        # 2. Get conversation for this session
        conversation = await get_webchat_conversation(db, channel, session_token)
        if not conversation:
            # No conversation exists yet, return empty messages
            return WebChatMessagesResponse(
                messages=[],
                has_more=False,
                session_token=session_token
            )
        
        # 3. Get messages for the conversation
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
            .limit(limit + 1)  # Get one extra to check if there are more
            .offset(offset)
        )
        
        messages = result.scalars().all()
        
        # Check if there are more messages
        has_more = len(messages) > limit
        if has_more:
            messages = messages[:-1]  # Remove the extra message
        
        # Convert to response format
        webchat_messages = [
            WebChatMessage(
                id=str(msg.id),
                content=msg.content,
                sender_type="user" if msg.role == "customer" else "assistant",
                timestamp=msg.created_at
            )
            for msg in messages
        ]
        
        return WebChatMessagesResponse(
            messages=webchat_messages,
            has_more=has_more,
            session_token=session_token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )