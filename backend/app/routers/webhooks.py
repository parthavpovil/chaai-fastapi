"""
Webhook Handlers
Handles incoming webhooks from external services (Resend, Telegram, WhatsApp, Instagram)
"""
from fastapi import APIRouter, Request, HTTPException, Header, Query, Depends
from fastapi.responses import PlainTextResponse
from typing import Optional
import hmac
import hashlib
import json
import logging

from app.config import settings
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/resend")
async def resend_webhook(
    request: Request,
    svix_id: Optional[str] = Header(None),
    svix_timestamp: Optional[str] = Header(None),
    svix_signature: Optional[str] = Header(None),
):
    """
    Handle Resend email webhooks
    
    Events:
    - email.sent: Email was accepted by Resend
    - email.delivered: Email was successfully delivered
    - email.delivery_delayed: Email delivery was delayed
    - email.complained: Recipient marked email as spam
    - email.bounced: Email bounced (hard or soft)
    - email.opened: Recipient opened the email
    - email.clicked: Recipient clicked a link in the email
    """
    # Get raw body for signature verification
    body = await request.body()
    
    # Verify webhook signature if secret is configured
    if settings.RESEND_WEBHOOK_SECRET:
        if not svix_signature:
            raise HTTPException(status_code=401, detail="Missing signature")
        
        # Verify signature
        if not verify_resend_signature(
            body=body,
            signature=svix_signature,
            timestamp=svix_timestamp,
            secret=settings.RESEND_WEBHOOK_SECRET
        ):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse event
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    event_type = event.get("type")
    data = event.get("data", {})
    
    # Handle different event types
    if event_type == "email.sent":
        await handle_email_sent(data)
    elif event_type == "email.delivered":
        await handle_email_delivered(data)
    elif event_type == "email.delivery_delayed":
        await handle_email_delayed(data)
    elif event_type == "email.complained":
        await handle_email_complained(data)
    elif event_type == "email.bounced":
        await handle_email_bounced(data)
    elif event_type == "email.opened":
        await handle_email_opened(data)
    elif event_type == "email.clicked":
        await handle_email_clicked(data)
    else:
        print(f"Unknown event type: {event_type}")
    
    return {"status": "ok"}


def verify_resend_signature(
    body: bytes,
    signature: str,
    timestamp: str,
    secret: str
) -> bool:
    """
    Verify Resend webhook signature using Svix standard
    
    Args:
        body: Raw request body
        signature: Signature from svix-signature header
        timestamp: Timestamp from svix-timestamp header
        secret: Webhook signing secret
        
    Returns:
        True if signature is valid, False otherwise
    """
    try:
        # Svix signature format: "v1,signature1 v1,signature2"
        signatures = {}
        for sig in signature.split(" "):
            version, value = sig.split(",", 1)
            signatures[version] = value
        
        # Get v1 signature
        expected_sig = signatures.get("v1")
        if not expected_sig:
            return False
        
        # Construct signed content: timestamp.body
        signed_content = f"{timestamp}.{body.decode('utf-8')}"
        
        # Compute HMAC
        computed_sig = hmac.new(
            secret.encode('utf-8'),
            signed_content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        return hmac.compare_digest(computed_sig, expected_sig)
        
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False


async def handle_email_sent(data: dict):
    """Handle email.sent event"""
    email_id = data.get("email_id")
    to = data.get("to")
    subject = data.get("subject")
    
    print(f"📤 Email sent: {email_id} to {to} - {subject}")
    
    # TODO: Update email status in database
    # await update_email_status(email_id, "sent")


async def handle_email_delivered(data: dict):
    """Handle email.delivered event"""
    email_id = data.get("email_id")
    to = data.get("to")
    
    print(f"✅ Email delivered: {email_id} to {to}")
    
    # TODO: Update email status in database
    # await update_email_status(email_id, "delivered")


async def handle_email_delayed(data: dict):
    """Handle email.delivery_delayed event"""
    email_id = data.get("email_id")
    to = data.get("to")
    
    print(f"⏳ Email delayed: {email_id} to {to}")
    
    # TODO: Update email status in database
    # await update_email_status(email_id, "delayed")


async def handle_email_complained(data: dict):
    """Handle email.complained event (marked as spam)"""
    email_id = data.get("email_id")
    to = data.get("to")
    
    print(f"⚠️ Email complained: {email_id} from {to}")
    
    # TODO: Mark user as unsubscribed or handle complaint
    # await handle_spam_complaint(to)


async def handle_email_bounced(data: dict):
    """Handle email.bounced event"""
    email_id = data.get("email_id")
    to = data.get("to")
    bounce_type = data.get("bounce_type")  # "hard" or "soft"
    
    print(f"❌ Email bounced ({bounce_type}): {email_id} to {to}")
    
    # TODO: Handle bounce (mark email as invalid if hard bounce)
    # if bounce_type == "hard":
    #     await mark_email_invalid(to)


async def handle_email_opened(data: dict):
    """Handle email.opened event"""
    email_id = data.get("email_id")
    to = data.get("to")
    
    print(f"👁️ Email opened: {email_id} by {to}")
    
    # TODO: Track email open
    # await track_email_open(email_id)


async def handle_email_clicked(data: dict):
    """Handle email.clicked event"""
    email_id = data.get("email_id")
    to = data.get("to")
    link = data.get("link")

    print(f"🔗 Email link clicked: {email_id} by {to} - {link}")

    # TODO: Track email click
    # await track_email_click(email_id, link)


# ─── Razorpay Webhook ─────────────────────────────────────────────────────────

@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Razorpay subscription lifecycle events."""
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return {"status": "ok"}

    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature", "")

    from app.services.razorpay_service import (
        verify_webhook_signature,
        handle_subscription_activated,
        handle_subscription_cancelled,
    )

    if not verify_webhook_signature(payload.decode("utf-8"), sig_header):
        logger.error("Razorpay webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid Razorpay signature")

    import json
    try:
        event = json.loads(payload)
    except Exception as e:
        logger.error(f"Razorpay webhook JSON parse error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("event", "")
    event_data = event.get("payload", {})

    try:
        if event_type == "subscription.activated":
            await handle_subscription_activated(event_data, db)
        elif event_type in ("subscription.cancelled", "subscription.halted", "subscription.completed"):
            await handle_subscription_cancelled(event_data, db)
        # subscription.charged is a no-op — subscription is already active
    except Exception as e:
        logger.error(f"Razorpay event handling error ({event_type}): {e}")

    return {"status": "ok"}


# ─── Channel Webhooks ─────────────────────────────────────────────────────────

async def _run_message_pipeline(
    db: AsyncSession,
    workspace_id: str,
    channel_id: str,
    message_data: dict,
    channel_type: str
) -> None:
    """Run the full message pipeline: process → flow check → escalate → RAG → persist response."""
    from app.services.message_processor import process_incoming_message, MessageProcessor
    from app.services.escalation_router import check_and_escalate_message
    from app.services.rag_engine import generate_rag_response
    from app.services.usage_tracker import track_message_usage
    from app.services.websocket_events import notify_new_message

    processing_result = await process_incoming_message(
        db=db,
        workspace_id=workspace_id,
        channel_id=channel_id,
        external_contact_id=message_data["external_contact_id"],
        content=message_data.get("content"),
        external_message_id=message_data.get("external_message_id"),
        contact_name=message_data.get("contact_name"),
        contact_data=message_data.get("contact_data", {}),
        message_metadata=message_data.get("message_metadata", {}),
        channel_type=channel_type,
        msg_type=message_data.get("msg_type", "text"),
        media_id=message_data.get("media_id"),
        media_mime_type=message_data.get("media_mime_type"),
        media_filename=message_data.get("media_filename"),
        location_lat=message_data.get("location_lat"),
        location_lng=message_data.get("location_lng"),
        location_name=message_data.get("location_name"),
    )

    conversation = processing_result["conversation"]
    conversation_id = str(conversation.id)
    user_message = processing_result["message"]
    user_message_id = str(user_message.id)

    await notify_new_message(
        db=db,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        message_id=user_message_id
    )

    # For non-text messages (media, location, reaction) skip RAG — no query to answer
    text_content = message_data.get("content") or ""
    msg_type = message_data.get("msg_type", "text")
    if msg_type != "text" or not text_content.strip():
        return

    # Flow engine check — runs before RAG for WhatsApp
    if channel_type == "whatsapp":
        try:
            from app.services.flow_engine import handle_message_with_flow_check
            from app.models.channel import Channel
            from sqlalchemy import select
            ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
            channel = ch_result.scalar_one_or_none()
            if channel:
                handled_by_flow = await handle_message_with_flow_check(
                    db=db,
                    conversation=conversation,
                    message=user_message,
                    workspace_id=workspace_id,
                    channel=channel,
                )
                if handled_by_flow:
                    return
        except Exception as e:
            logger.error(f"Flow engine error: {e}")

    # AI Agent routing — runs after flow engine, before escalation check + RAG
    from sqlalchemy import select as _select
    from app.models.workspace import Workspace as _Workspace
    workspace_result = await db.execute(
        _select(_Workspace).where(_Workspace.id == workspace_id)
    )
    _workspace = workspace_result.scalar_one_or_none()
    _ai_mode = (_workspace.meta or {}).get("ai_mode", "rag") if _workspace else "rag"

    if _ai_mode == "ai_agent":
        try:
            from app.services.ai_agent_runner import ai_agent_runner
            from app.services.websocket_events import notify_new_message
            from app.services.message_processor import MessageProcessor

            agent_result = await ai_agent_runner.run(
                db=db,
                conversation_id=conversation_id,
                new_message=text_content,
                workspace_id=workspace_id,
                channel_id=channel_id,
            )
            if agent_result.handled:
                processor = MessageProcessor(db)
                ai_msg = await processor.create_message(
                    conversation_id=conversation_id,
                    content=agent_result.reply,
                    role="ai",
                    channel_type=channel_type,
                    metadata={"ai_agent": True, "escalated": agent_result.escalated},
                )
                await notify_new_message(
                    db=db,
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    message_id=str(ai_msg.id),
                )
                return
        except Exception as e:
            logger.error(f"AI agent runner error for conversation {conversation_id}: {e}")

    escalation_result = await check_and_escalate_message(
        db=db,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        message_content=text_content
    )

    if not escalation_result:
        try:
            rag_result = await generate_rag_response(
                db=db,
                workspace_id=workspace_id,
                query=text_content,
                conversation_id=conversation_id,
                max_tokens=300
            )

            processor = MessageProcessor(db)
            await processor.create_message(
                conversation_id=conversation_id,
                content=rag_result["response"],
                role="assistant",
                channel_type=channel_type,
                metadata={
                    "rag_used": True,
                    "input_tokens": rag_result["input_tokens"],
                    "output_tokens": rag_result["output_tokens"],
                }
            )

            await track_message_usage(
                db=db,
                workspace_id=workspace_id,
                input_tokens=rag_result["input_tokens"],
                output_tokens=rag_result["output_tokens"]
            )

            await notify_new_message(
                db=db,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=user_message_id
            )
        except Exception as e:
            logger.error(f"RAG response failed for {channel_type} conversation {conversation_id}: {e}")


# ── Telegram ──────────────────────────────────────────────────────────────────

@router.post("/telegram/{bot_token}")
async def telegram_webhook(
    bot_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Receive incoming Telegram messages."""
    payload = await request.body()
    headers = dict(request.headers)

    try:
        from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
        result = await WebhookHandlers(db).handle_telegram_webhook(payload, headers, bot_token)

        if result.get("status") == "success":
            try:
                await _run_message_pipeline(
                    db=db,
                    workspace_id=str(result["workspace_id"]),
                    channel_id=str(result["channel_id"]),
                    message_data=result["message_data"],
                    channel_type="telegram"
                )
            except Exception as e:
                logger.error(f"Telegram pipeline error: {e}")

    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")

    # Always return 200 to prevent Telegram retries
    return {"ok": True}


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@router.get("/whatsapp/{phone_number_id}", response_class=PlainTextResponse)
async def whatsapp_verify(
    phone_number_id: str,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta hub verification for WhatsApp webhook subscription."""
    if hub_mode == "subscribe" and hub_verify_token:
        expected = settings.META_VERIFY_TOKEN
        if expected and hub_verify_token != expected:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
        return hub_challenge or ""
    raise HTTPException(status_code=400, detail="Invalid verification request")


@router.post("/whatsapp/{phone_number_id}")
async def whatsapp_webhook(
    phone_number_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Receive incoming WhatsApp messages."""
    payload = await request.body()
    headers = dict(request.headers)

    try:
        from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
        result = await WebhookHandlers(db).handle_whatsapp_webhook(payload, headers, phone_number_id)

        status = result.get("status")

        if status == "success":
            try:
                await _run_message_pipeline(
                    db=db,
                    workspace_id=str(result["workspace_id"]),
                    channel_id=str(result["channel_id"]),
                    message_data=result["message_data"],
                    channel_type="whatsapp"
                )
            except Exception as e:
                logger.error(f"WhatsApp pipeline error: {e}")

        elif status == "status_update":
            try:
                from app.services.message_processor import MessageProcessor
                from app.services.websocket_events import notify_message_status_update
                processor = MessageProcessor(db)
                workspace_id = str(result["workspace_id"])
                for s in result.get("statuses", []):
                    msg = await processor.update_message_delivery_status(
                        whatsapp_msg_id=s["whatsapp_msg_id"],
                        status=s["status"],
                        timestamp=s["timestamp"],
                        workspace_id=workspace_id,
                        error=s.get("error"),
                    )
                    if msg:
                        await notify_message_status_update(
                            db=db,
                            workspace_id=workspace_id,
                            message_id=str(msg.id),
                            whatsapp_msg_id=s["whatsapp_msg_id"],
                            status=s["status"],
                            timestamp=s["timestamp"],
                        )
            except Exception as e:
                logger.error(f"WhatsApp status update error: {e}")

    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}")

    return {"status": "ok"}


# ── Instagram ─────────────────────────────────────────────────────────────────

@router.get("/instagram/{page_id}", response_class=PlainTextResponse)
async def instagram_verify(
    page_id: str,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta hub verification for Instagram webhook subscription."""
    if hub_mode == "subscribe" and hub_verify_token:
        expected = settings.META_VERIFY_TOKEN
        if expected and hub_verify_token != expected:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
        return hub_challenge or ""
    raise HTTPException(status_code=400, detail="Invalid verification request")


@router.post("/instagram/{page_id}")
async def instagram_webhook(
    page_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Receive incoming Instagram messages."""
    payload = await request.body()
    headers = dict(request.headers)

    try:
        from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
        result = await WebhookHandlers(db).handle_instagram_webhook(payload, headers, page_id)

        if result.get("status") == "success":
            try:
                await _run_message_pipeline(
                    db=db,
                    workspace_id=str(result["workspace_id"]),
                    channel_id=str(result["channel_id"]),
                    message_data=result["message_data"],
                    channel_type="instagram"
                )
            except Exception as e:
                logger.error(f"Instagram pipeline error: {e}")

    except Exception as e:
        logger.error(f"Instagram webhook error: {e}")

    return {"status": "ok"}
