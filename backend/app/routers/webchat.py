"""
WebChat Public API Router
Public endpoints for website chat widget functionality
"""
import logging
import mimetypes
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field, model_validator

from app.database import get_db
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.message_processor import (
    MessageProcessor, process_incoming_message, MessageProcessingError,
    BlockedContactError, OutsideBusinessHoursError,
)
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
    message: Optional[str] = Field(None, min_length=1, max_length=2000, description="Message content")
    # Media fields (for pre-uploaded files)
    media_url: Optional[str] = Field(None, description="Pre-uploaded R2 URL")
    media_mime_type: Optional[str] = Field(None, description="MIME type of the media")
    media_filename: Optional[str] = Field(None, max_length=255, description="Original filename")
    media_size: Optional[int] = Field(None, description="File size in bytes")
    message_type: Optional[str] = Field(None, description="text|image|video|audio|document")
    contact_name: Optional[str] = Field(None, max_length=100, description="Contact display name")
    contact_email: Optional[str] = Field(None, max_length=254, description="Contact email address")
    contact_phone: Optional[str] = Field(None, max_length=20, description="Contact phone number")
    external_id: Optional[str] = Field(None, max_length=255, description="Business's internal customer ID")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Customer context (plan, orders, city, etc.)")

    @model_validator(mode="after")
    def require_message_or_media(self) -> "WebChatSendRequest":
        if not self.message and not self.media_url:
            raise ValueError("Either 'message' or 'media_url' must be provided")
        return self


class WebChatSendResponse(BaseModel):
    """Response schema for WebChat send endpoint"""
    success: bool
    session_token: str
    message_id: str
    response: Optional[str] = None
    error: Optional[str] = None


class WebChatUploadResponse(BaseModel):
    """Response schema for WebChat file upload endpoint"""
    url: str
    mime_type: str
    size: int
    filename: str
    message_type: str  # image | video | audio | document


class WebChatMessage(BaseModel):
    """WebChat message schema"""
    id: str
    content: Optional[str] = None
    sender_type: str  # "user" or "assistant"
    timestamp: datetime
    msg_type: Optional[str] = "text"
    media_url: Optional[str] = None
    media_mime_type: Optional[str] = None
    media_filename: Optional[str] = None
    media_size: Optional[int] = None

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
    workspace_id: str
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
                # Decrypt config - each field is encrypted separately
                decrypted_config = {}
                for key, value in channel.config.items():
                    if isinstance(value, str) and value:
                        try:
                            decrypted_config[key] = decrypt_credential(value)
                        except Exception:
                            # If decryption fails, use value as-is
                            decrypted_config[key] = value
                    else:
                        decrypted_config[key] = value
                
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
        .where(Contact.external_id == session_token)
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        return None
    
    # Find active conversation for this contact
    result = await db.execute(
        select(Conversation)
        .where(Conversation.workspace_id == channel.workspace_id)
        .where(Conversation.contact_id == contact.id)
        .where(Conversation.channel_type == "webchat")
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


def _infer_msg_type(mime_type: Optional[str]) -> str:
    """Infer message type from MIME type."""
    if not mime_type:
        return "document"
    prefix = mime_type.split("/")[0]
    return prefix if prefix in ("image", "video", "audio") else "document"


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
        
        # Decrypt the channel configuration
        # Note: channel.config is a dict where each value is encrypted separately
        try:
            config = {}
            if not channel.config:
                raise HTTPException(
                    status_code=500,
                    detail="WebChat configuration is empty"
                )
            
            # Decrypt each field in the config
            for key, value in channel.config.items():
                if isinstance(value, str) and value:
                    try:
                        config[key] = decrypt_credential(value)
                    except Exception:
                        # If decryption fails, use the value as-is (might not be encrypted)
                        config[key] = value
                else:
                    config[key] = value
                    
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to load WebChat configuration: {str(e)}"
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
            workspace_id=str(channel.workspace_id),
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
            # Derive message type for media messages
            msg_type = request.message_type or (
                "text" if not request.media_url else _infer_msg_type(request.media_mime_type)
            )
            # For media-only messages, pass a placeholder so the AI has context
            message_content = request.message or "[User sent a file]"

            # Step 1: Process incoming message
            processing_result = await process_incoming_message(
                db=db,
                workspace_id=str(channel.workspace_id),
                channel_id=str(channel.id),
                external_contact_id=request.external_id or session_token,
                content=message_content,
                external_message_id=None,  # WebChat messages don't have external IDs
                contact_name=request.contact_name or f"WebChat User {session_token[:8]}",
                contact_data={
                    "session_token": session_token,
                    "email": request.contact_email,
                    "phone": request.contact_phone,
                    "metadata": request.metadata,
                },
                message_metadata={"session_token": session_token}
            )

            conversation_id = str(processing_result["conversation"].id)
            user_message_id = str(processing_result["message"].id)

            # Patch media fields onto the created message if media was uploaded
            if request.media_url:
                msg_obj = processing_result["message"]
                msg_obj.media_url = request.media_url
                msg_obj.media_mime_type = request.media_mime_type
                msg_obj.media_filename = request.media_filename
                msg_obj.media_size = request.media_size
                msg_obj.msg_type = msg_type
                await db.commit()

            # Send WebSocket notification for customer message
            await notify_new_message(
                db=db,
                workspace_id=str(channel.workspace_id),
                conversation_id=conversation_id,
                message_id=user_message_id
            )

            processor = MessageProcessor(db)

            # Step 2: Routing mode resolution — read capability flags
            from sqlalchemy import select as _wc_select
            from app.models.workspace import Workspace as _WC_Workspace
            _wc_ws_result = await db.execute(
                _wc_select(_WC_Workspace).where(_WC_Workspace.id == channel.workspace_id)
            )
            _wc_ws = _wc_ws_result.scalar_one_or_none()
            _wc_meta          = (_wc_ws.meta or {}) if _wc_ws else {}
            _wc_ai_mode       = _wc_meta.get("ai_mode", "rag")
            _wc_ai_enabled    = _wc_ws.ai_enabled if _wc_ws is not None else True
            _wc_auto_esc      = _wc_ws.auto_escalation_enabled if _wc_ws is not None else True
            _wc_agents        = _wc_ws.agents_enabled if _wc_ws is not None else False

            response_content = None

            # Branch 1: AI disabled + human agents enabled → direct routing, no LLM
            if not _wc_ai_enabled and _wc_agents:
                try:
                    from app.services.escalation_router import EscalationRouter
                    from app.services.websocket_events import notify_customer_new_message
                    esc_result = await EscalationRouter(db).process_escalation(
                        conversation_id=conversation_id,
                        workspace_id=str(channel.workspace_id),
                        escalation_reason="direct_routing",
                        classification_data={
                            "should_escalate": True,
                            "confidence": 1.0,
                            "reason": "direct_routing",
                            "category": "routing_mode",
                            "classification_method": "workspace_config",
                        },
                        priority="medium",
                    )
                    # Push the acknowledgment message to the customer via WebSocket.
                    # process_escalation already stored it in the DB; no need to also
                    # echo it back in the HTTP response (that would show it twice).
                    ack_msg_id = esc_result.get("acknowledgment_message_id")
                    if ack_msg_id:
                        await notify_customer_new_message(
                            db=db,
                            workspace_id=str(channel.workspace_id),
                            session_token=session_token,
                            message_id=str(ack_msg_id),
                        )
                except Exception as e:
                    logger.error(f"Direct routing escalation failed for webchat {conversation_id}: {e}")
                response_content = None  # delivered via WebSocket / message polling

            # Branch 2: AI disabled, no human agents → receive silently
            elif not _wc_ai_enabled:
                response_content = None

            else:
                # Branch 3: AI enabled — AI agent mode
                _wc_handled = False
                if _wc_ai_mode == "ai_agent":
                    try:
                        from app.services.ai_agent_runner import ai_agent_runner
                        agent_result = await ai_agent_runner.run(
                            db=db,
                            conversation_id=conversation_id,
                            new_message=message_content,
                            workspace_id=str(channel.workspace_id),
                            channel_id=str(channel.id),
                        )
                        if agent_result.handled:
                            _wc_handled = True
                            response_content = agent_result.reply
                            ai_msg = await processor.create_message(
                                conversation_id=conversation_id,
                                content=agent_result.reply,
                                role="assistant",
                                channel_type="webchat",
                                metadata={"ai_agent": True, "escalated": agent_result.escalated},
                            )
                            await notify_new_message(
                                db=db,
                                workspace_id=str(channel.workspace_id),
                                conversation_id=conversation_id,
                                message_id=str(ai_msg.id),
                            )
                            from app.services.websocket_events import notify_customer_new_message
                            await notify_customer_new_message(
                                db=db,
                                workspace_id=str(channel.workspace_id),
                                session_token=session_token,
                                message_id=str(ai_msg.id),
                            )
                    except Exception as e:
                        logger.error(f"AI agent runner error for webchat {conversation_id}: {e}")

                if not _wc_handled:
                    # Auto-escalation check — only when both agents and auto-escalation are enabled
                    escalation_result = None
                    if _wc_agents and _wc_auto_esc:
                        escalation_result = await check_and_escalate_message(
                            db=db,
                            conversation_id=conversation_id,
                            workspace_id=str(channel.workspace_id),
                            message_content=message_content
                        )

                    if not escalation_result:
                        # RAG response
                        try:
                            rag_result = await generate_rag_response(
                                db=db,
                                workspace_id=str(channel.workspace_id),
                                query=message_content,
                                conversation_id=conversation_id,
                                max_tokens=300
                            )

                            response_content = rag_result["response"]
                            input_tokens = rag_result["input_tokens"]
                            output_tokens = rag_result["output_tokens"]

                            ai_message = await processor.create_message(
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

                            await track_message_usage(
                                db=db,
                                workspace_id=str(channel.workspace_id),
                                input_tokens=input_tokens,
                                output_tokens=output_tokens
                            )

                            if ai_message:
                                await notify_new_message(
                                    db=db,
                                    workspace_id=str(channel.workspace_id),
                                    conversation_id=conversation_id,
                                    message_id=str(ai_message.id),
                                )
                                from app.services.websocket_events import notify_customer_new_message
                                await notify_customer_new_message(
                                    db=db,
                                    workspace_id=str(channel.workspace_id),
                                    session_token=session_token,
                                    message_id=str(ai_message.id),
                                )

                        except Exception as e:
                            logger.error(f"RAG response generation failed: {e}", exc_info=True)
                            response_content = "I'm sorry, I'm having trouble processing your request right now. Please try again later."
                    else:
                        response_content = "Thank you for your message. I've escalated your request to our support team who will get back to you shortly."
            
        except BlockedContactError:
            # Return a polite response without revealing the contact is blocked
            return WebChatSendResponse(
                success=True,
                session_token=session_token,
                message_id="",
                response="We're unable to process your message at this time.",
                error=None,
            )
        except OutsideBusinessHoursError as e:
            return WebChatSendResponse(
                success=True,
                session_token=session_token,
                message_id="",
                response=e.outside_hours_message,
                error=None,
            )
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
            logger.error(f"WebChat message processing failed: {e}", exc_info=True)
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


@router.post("/upload", response_model=WebChatUploadResponse)
async def upload_webchat_file(
    widget_id: str = Form(...),
    session_token: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a file attachment through the WebChat widget.

    Accepts multipart form data with widget_id, session_token, and a file.
    Uploads the file to Cloudflare R2 and returns the public URL.
    An active session (prior text message) is required before uploading.
    """
    from app.services.r2_storage import upload_webchat_media

    # 1. Validate widget
    channel = await get_webchat_channel_by_widget_id(db, widget_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Widget not found or inactive")

    # 2. Require an existing session
    conversation = await get_webchat_conversation(db, channel, session_token)
    if not conversation:
        raise HTTPException(
            status_code=401,
            detail="No active session. Send a text message first to start a conversation."
        )

    # 3. Rate limit (shared bucket with /send)
    try:
        await check_webchat_rate_limit(
            db=db,
            session_token=session_token,
            workspace_id=str(channel.workspace_id)
        )
    except RateLimitExceededError as e:
        return JSONResponse(status_code=429, content={"detail": str(e)})

    # 4. Read file bytes
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    # 5. Determine MIME type
    mime_type = file.content_type or ""
    if not mime_type or mime_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(file.filename or "")
        mime_type = guessed or "application/octet-stream"

    # 6. Upload to R2
    try:
        result = await upload_webchat_media(
            file_bytes=file_bytes,
            mime_type=mime_type,
            workspace_id=str(channel.workspace_id),
            original_filename=file.filename or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    return WebChatUploadResponse(
        url=result["url"],
        mime_type=result["mime_type"],
        size=result["size_bytes"],
        filename=result["filename"],
        message_type=_infer_msg_type(result["mime_type"]),
    )


# ─── CSAT Endpoints (public, no auth) ────────────────────────────────────────

class CSATSubmitRequest(BaseModel):
    token: str = Field(..., description="CSAT JWT token from csat_prompt event")
    rating: int = Field(..., ge=1, le=5, description="Satisfaction rating 1-5")
    comment: Optional[str] = Field(None, max_length=1000)


class CSATSubmitResponse(BaseModel):
    success: bool
    message: str


class CSATTokenResponse(BaseModel):
    valid: bool
    conversation_id: Optional[str] = None
    workspace_id: Optional[str] = None


@router.post("/csat", response_model=CSATSubmitResponse)
async def submit_csat_rating(
    request: CSATSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit a CSAT rating for a resolved conversation (no auth required)."""
    from app.services.csat_service import decode_csat_token
    from app.models.csat_rating import CSATRating

    payload = decode_csat_token(request.token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired CSAT token")

    conversation_id = payload["sub"]
    workspace_id = payload["workspace_id"]

    # Verify conversation exists and is resolved
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.id == UUID(conversation_id))
        .where(Conversation.workspace_id == UUID(workspace_id))
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status != "resolved":
        raise HTTPException(status_code=400, detail="Conversation is not resolved")

    # Check for duplicate rating
    existing = await db.execute(
        select(CSATRating).where(CSATRating.conversation_id == UUID(conversation_id))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Rating already submitted for this conversation")

    rating = CSATRating(
        conversation_id=UUID(conversation_id),
        workspace_id=UUID(workspace_id),
        contact_id=conversation.contact_id,
        rating=request.rating,
        comment=request.comment,
    )
    db.add(rating)
    await db.commit()

    # Fire outbound webhook (fire-and-forget)
    try:
        import asyncio
        from app.services.outbound_webhook_service import trigger_event
        asyncio.create_task(trigger_event(
            db=db,
            workspace_id=workspace_id,
            event_type="csat.submitted",
            payload={
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "rating": request.rating,
                "comment": request.comment,
            }
        ))
    except Exception:
        pass

    return CSATSubmitResponse(success=True, message="Thank you for your feedback!")


@router.get("/csat/{token}", response_model=CSATTokenResponse)
async def validate_csat_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Validate a CSAT token and return conversation context (no auth required)."""
    from app.services.csat_service import decode_csat_token

    payload = decode_csat_token(token)
    if not payload:
        return CSATTokenResponse(valid=False)

    return CSATTokenResponse(
        valid=True,
        conversation_id=payload["sub"],
        workspace_id=payload["workspace_id"],
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
                timestamp=msg.created_at,
                msg_type=msg.msg_type or "text",
                media_url=msg.media_url,
                media_mime_type=msg.media_mime_type,
                media_filename=msg.media_filename,
                media_size=msg.media_size,
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