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
    db: AsyncSession = Depends(get_db),
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

        if not verify_resend_signature(
            body=body,
            signature=svix_signature,
            timestamp=svix_timestamp,
            secret=settings.RESEND_WEBHOOK_SECRET,
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
        await handle_email_sent(data, db)
    elif event_type == "email.delivered":
        await handle_email_delivered(data, db)
    elif event_type == "email.delivery_delayed":
        await handle_email_delayed(data, db)
    elif event_type == "email.complained":
        await handle_email_complained(data, db)
    elif event_type == "email.bounced":
        await handle_email_bounced(data, db)
    elif event_type == "email.opened":
        await handle_email_opened(data, db)
    elif event_type == "email.clicked":
        await handle_email_clicked(data, db)
    else:
        logger.warning("Resend webhook received unknown event type: %s", event_type)

    return {"status": "ok"}


def verify_resend_signature(
    body: bytes,
    signature: str,
    timestamp: str,
    secret: str
) -> bool:
    """
    Verify Resend webhook signature using Svix standard.

    Only catches parsing / encoding errors (KeyError, ValueError, UnicodeDecodeError).
    Other exceptions propagate so they are visible in Sentry rather than
    silently returning False and masking broken config or library issues.
    """
    try:
        # Svix signature format: "v1,signature1 v1,signature2"
        signatures = {}
        for sig in signature.split(" "):
            version, value = sig.split(",", 1)
            signatures[version] = value

        expected_sig = signatures.get("v1")
        if not expected_sig:
            return False

        signed_content = f"{timestamp}.{body.decode('utf-8')}"
        computed_sig = hmac.new(
            secret.encode('utf-8'),
            signed_content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed_sig, expected_sig)

    except (KeyError, ValueError, UnicodeDecodeError) as e:
        logger.warning("Resend signature verification error: %s", e)
        return False


# ─── Inbound channel signature helpers ───────────────────────────────────────

def _verify_meta_signature(payload: bytes, sig_header: str, app_secret: str) -> None:
    """
    Raise HTTPException(401) if the Meta X-Hub-Signature-256 header is absent
    or does not match HMAC-SHA256(app_secret, payload).

    Meta (WhatsApp + Instagram) sends:
        X-Hub-Signature-256: sha256=<lowercase_hex_digest>
    """
    if not sig_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or malformed X-Hub-Signature-256")
    expected = sig_header[7:]  # strip "sha256="
    computed = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _verify_telegram_secret_token(header_value: str, expected: str) -> None:
    """
    Raise HTTPException(401) if X-Telegram-Bot-Api-Secret-Token doesn't match.
    Uses hmac.compare_digest to prevent timing-based leaks.
    """
    if not hmac.compare_digest(header_value, expected):
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")


async def _persist_email_log(
    db: AsyncSession,
    event_type: str,
    data: dict,
) -> None:
    """Create an EmailLog row and commit it."""
    from app.models.email_log import EmailLog
    from uuid import uuid4

    email_id = data.get("email_id") or data.get("id") or str(uuid4())
    recipient = data.get("to")
    if isinstance(recipient, list):
        recipient = ", ".join(recipient)
    subject = data.get("subject")

    log_entry = EmailLog(
        email_id=email_id,
        event_type=event_type,
        recipient=recipient,
        subject=subject,
        extra_data=data,
    )
    db.add(log_entry)
    await db.commit()


async def handle_email_sent(data: dict, db: AsyncSession) -> None:
    """Handle email.sent event — email accepted by Resend."""
    email_id = data.get("email_id")
    to = data.get("to")
    subject = data.get("subject")
    logger.info("Email sent: email_id=%s to=%s subject=%s", email_id, to, subject)
    await _persist_email_log(db, "sent", data)


async def handle_email_delivered(data: dict, db: AsyncSession) -> None:
    """Handle email.delivered event — successfully delivered to recipient."""
    email_id = data.get("email_id")
    to = data.get("to")
    logger.info("Email delivered: email_id=%s to=%s", email_id, to)
    await _persist_email_log(db, "delivered", data)


async def handle_email_delayed(data: dict, db: AsyncSession) -> None:
    """Handle email.delivery_delayed event."""
    email_id = data.get("email_id")
    to = data.get("to")
    logger.warning("Email delivery delayed: email_id=%s to=%s", email_id, to)
    await _persist_email_log(db, "delayed", data)


async def handle_email_complained(data: dict, db: AsyncSession) -> None:
    """Handle email.complained event — recipient marked email as spam."""
    email_id = data.get("email_id")
    to = data.get("to")
    logger.warning("Spam complaint received: email_id=%s from=%s", email_id, to)
    await _persist_email_log(db, "complained", data)


async def handle_email_bounced(data: dict, db: AsyncSession) -> None:
    """Handle email.bounced event — hard bounces indicate an invalid address."""
    email_id = data.get("email_id")
    to = data.get("to")
    bounce_type = data.get("bounce_type")  # "hard" or "soft"
    if bounce_type == "hard":
        logger.warning(
            "Hard bounce received — address may be invalid: email_id=%s to=%s",
            email_id,
            to,
        )
    else:
        logger.info("Soft bounce received: email_id=%s to=%s bounce_type=%s", email_id, to, bounce_type)
    await _persist_email_log(db, "bounced", data)


async def handle_email_opened(data: dict, db: AsyncSession) -> None:
    """Handle email.opened event."""
    email_id = data.get("email_id")
    to = data.get("to")
    logger.info("Email opened: email_id=%s by=%s", email_id, to)
    await _persist_email_log(db, "opened", data)


async def handle_email_clicked(data: dict, db: AsyncSession) -> None:
    """Handle email.clicked event."""
    email_id = data.get("email_id")
    to = data.get("to")
    link = data.get("link")
    logger.info("Email link clicked: email_id=%s by=%s link=%s", email_id, to, link)
    await _persist_email_log(db, "clicked", data)


# ─── Razorpay Webhook ─────────────────────────────────────────────────────────

_RZP_EVENT_TTL = 172_800  # 48 h — covers Razorpay's retry window


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Razorpay subscription lifecycle events.

    Idempotency: each Razorpay event carries a unique `id` field. We claim it
    in Redis with a 48-hour TTL before processing. Duplicate deliveries return
    200 immediately. If processing fails, the key is deleted so the next retry
    can re-claim it, and we return 500 so Razorpay actually retries.
    """
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
        logger.error("Razorpay webhook JSON parse error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("event", "")
    event_id = event.get("id", "")
    event_data = event.get("payload", {})

    # ── Idempotency gate ──────────────────────────────────────────────────────
    import redis.asyncio as _aioredis

    idempotency_key = f"rzp_event:{event_id}" if event_id else None
    redis_client = None

    if idempotency_key:
        try:
            redis_client = _aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            acquired = await redis_client.set(idempotency_key, "1", nx=True, ex=_RZP_EVENT_TTL)
            if not acquired:
                logger.info("Razorpay event %s already processed — skipping", event_id)
                return {"status": "ok"}
        except Exception as e:
            logger.warning("Razorpay idempotency Redis error (proceeding): %s", e)
            redis_client = None  # don't try to delete a key we never set

    # ── Process event ─────────────────────────────────────────────────────────
    try:
        if event_type == "subscription.activated":
            await handle_subscription_activated(event_data, db)
        elif event_type in ("subscription.cancelled", "subscription.halted", "subscription.completed"):
            await handle_subscription_cancelled(event_data, db)
        # subscription.charged is a no-op — subscription is already active
    except Exception as e:
        logger.error("Razorpay event handling error (%s): %s", event_type, e, exc_info=True)
        # Release the idempotency key so Razorpay's next retry can re-claim it.
        if idempotency_key and redis_client:
            try:
                await redis_client.delete(idempotency_key)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Event processing failed")
    finally:
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass

    return {"status": "ok"}


# ─── Channel Webhooks ─────────────────────────────────────────────────────────

# 24-hour TTL covers all carrier retry windows (Telegram: 60 s; Meta: up to 72 h but
# messages are deduplicated by external_message_id unique constraint as a second layer).
_INBOUND_MSG_TTL = 86_400  # 24 hours


async def _claim_inbound_message(provider: str, external_message_id: str) -> bool:
    """
    Claim an inbound message idempotency slot in Redis.

    Returns True if this is the *first* time we've seen this (provider, id) pair
    (i.e. the caller should process it), False if it was already claimed.

    Fail-open: if Redis is unavailable, returns True so no messages are silently
    dropped.  The external_message_id unique DB constraint acts as a second guard.
    """
    try:
        import redis.asyncio as _aioredis
        key = f"inbound:{provider}:{external_message_id}"
        r = _aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            acquired = await r.set(key, "1", nx=True, ex=_INBOUND_MSG_TTL)
            return bool(acquired)
        finally:
            await r.aclose()
    except Exception as e:
        logger.warning("Inbound idempotency Redis error for %s/%s (fail-open): %s",
                       provider, external_message_id, e)
        return True


async def _run_pipeline_with_own_session(
    workspace_id: str,
    channel_id: str,
    message_data: dict,
    channel_type: str,
    telegram_context: dict = None,
    whatsapp_context: dict = None,
    instagram_context: dict = None,
) -> None:
    """Open a fresh AsyncSession and run _run_message_pipeline.

    Used as the body of safe_create_task so the HTTP response is returned
    immediately (before the 60-90 s RAG call), meeting the carrier timeout
    budget (Meta: 5-10 s, Telegram: 60 s).
    """
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await _run_message_pipeline(
            db=db,
            workspace_id=workspace_id,
            channel_id=channel_id,
            message_data=message_data,
            channel_type=channel_type,
            telegram_context=telegram_context,
            whatsapp_context=whatsapp_context,
            instagram_context=instagram_context,
        )


async def _run_message_pipeline(
    db: AsyncSession,
    workspace_id: str,
    channel_id: str,
    message_data: dict,
    channel_type: str,
    telegram_context: dict = None,
    whatsapp_context: dict = None,
    instagram_context: dict = None,
) -> None:
    """Run the full message pipeline: process → flow check → escalate → RAG → persist response.

    Args:
        telegram_context: For Telegram — keys: bot_token, chat_id
        whatsapp_context: For WhatsApp — keys: access_token, phone_number_id, recipient_phone
        instagram_context: For Instagram — keys: access_token, page_id, recipient_id
    """
    from app.services.message_processor import process_incoming_message, MessageProcessor
    from app.services.escalation_router import check_and_escalate_message
    from app.services.rag_engine import generate_rag_response
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

    # Routing mode resolution — read all three capability flags from workspace
    from sqlalchemy import select as _select
    from app.models.workspace import Workspace as _Workspace
    workspace_result = await db.execute(
        _select(_Workspace).where(_Workspace.id == workspace_id)
    )
    _workspace = workspace_result.scalar_one_or_none()
    _meta             = (_workspace.meta or {}) if _workspace else {}
    _ai_mode          = _meta.get("ai_mode", "rag")
    _ai_enabled       = _workspace.ai_enabled if _workspace is not None else True
    _auto_esc_enabled = _workspace.auto_escalation_enabled if _workspace is not None else True
    _agents_enabled   = _workspace.agents_enabled if _workspace is not None else False

    # Branch 1: AI disabled + human agents enabled → route directly to human, no LLM call
    if not _ai_enabled and _agents_enabled:
        try:
            from app.services.escalation_router import EscalationRouter
            await EscalationRouter(db).process_escalation(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
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
        except Exception as e:
            logger.error(f"Direct routing escalation failed for conversation {conversation_id}: {e}")

        # Send escalation acknowledgment back through the channel
        ack_text = (
            _workspace.escalation_message_with_agents
            if _workspace and _workspace.escalation_message_with_agents
            else "Thank you for your message. I've escalated your request to one of our human agents who will assist you shortly."
        )
        if channel_type == "telegram" and telegram_context:
            from app.services.telegram_sender import send_telegram_message
            sent = await send_telegram_message(
                bot_token=telegram_context["bot_token"],
                chat_id=telegram_context["chat_id"],
                text=ack_text,
            )
            if not sent:
                logger.error("Failed to deliver direct-routing ack to Telegram for conversation_id=%s", conversation_id)
        elif channel_type == "whatsapp" and whatsapp_context:
            from app.services.whatsapp_sender import send_whatsapp_message
            sent = await send_whatsapp_message(
                access_token=whatsapp_context["access_token"],
                phone_number_id=whatsapp_context["phone_number_id"],
                to=whatsapp_context["recipient_phone"],
                text=ack_text,
            )
            if not sent:
                logger.error("Failed to deliver direct-routing ack to WhatsApp for conversation_id=%s", conversation_id)
        elif channel_type == "instagram" and instagram_context:
            from app.services.instagram_sender import send_instagram_message
            sent = await send_instagram_message(
                access_token=instagram_context["access_token"],
                page_id=instagram_context["page_id"],
                recipient_id=instagram_context["recipient_id"],
                text=ack_text,
            )
            if not sent:
                logger.error("Failed to deliver direct-routing ack to Instagram for conversation_id=%s", conversation_id)
        return

    # Branch 2: AI disabled, no human agents → receive message silently, no reply
    if not _ai_enabled:
        return

    # Branch 3: AI enabled — AI agent mode
    if _ai_mode == "ai_agent":
        agent_reply_text = None
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
                agent_reply_text = agent_result.reply
                processor = MessageProcessor(db)
                ai_msg = await processor.create_message(
                    conversation_id=conversation_id,
                    content=agent_result.reply,
                    role="assistant",
                    channel_type=channel_type,
                    metadata={"ai_agent": True, "escalated": agent_result.escalated},
                )
                await notify_new_message(
                    db=db,
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    message_id=str(ai_msg.id),
                )
        except Exception as e:
            logger.error(f"AI agent runner error for conversation {conversation_id}: {e}")

        if agent_reply_text is not None:
            if channel_type == "telegram" and telegram_context:
                from app.services.telegram_sender import send_telegram_message
                sent = await send_telegram_message(
                    bot_token=telegram_context["bot_token"],
                    chat_id=telegram_context["chat_id"],
                    text=agent_reply_text,
                )
                if not sent:
                    logger.error(
                        "Failed to deliver AI agent reply to Telegram for conversation_id=%s chat_id=%s",
                        conversation_id,
                        telegram_context["chat_id"],
                    )
            elif channel_type == "whatsapp" and whatsapp_context:
                from app.services.whatsapp_sender import send_whatsapp_message
                sent = await send_whatsapp_message(
                    access_token=whatsapp_context["access_token"],
                    phone_number_id=whatsapp_context["phone_number_id"],
                    to=whatsapp_context["recipient_phone"],
                    text=agent_reply_text,
                )
                if not sent:
                    logger.error(
                        "Failed to deliver AI agent reply to WhatsApp for conversation_id=%s", conversation_id
                    )
            elif channel_type == "instagram" and instagram_context:
                from app.services.instagram_sender import send_instagram_message
                sent = await send_instagram_message(
                    access_token=instagram_context["access_token"],
                    page_id=instagram_context["page_id"],
                    recipient_id=instagram_context["recipient_id"],
                    text=agent_reply_text,
                )
                if not sent:
                    logger.error(
                        "Failed to deliver AI agent reply to Instagram for conversation_id=%s", conversation_id
                    )
            return

    # Auto-escalation check — only runs when both agents and auto-escalation are enabled
    escalation_result = None
    if _agents_enabled and _auto_esc_enabled:
        escalation_result = await check_and_escalate_message(
            db=db,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            message_content=text_content
        )

    if not escalation_result:
        rag_response_text = None
        ai_msg = None
        try:
            rag_result = await generate_rag_response(
                db=db,
                workspace_id=workspace_id,
                query=text_content,
                conversation_id=conversation_id,
                max_tokens=300
            )
            rag_response_text = rag_result.get("response")
            logger.info(f"✅ RAG response generated: {len(rag_response_text)} chars")

            processor = MessageProcessor(db)
            ai_msg = await processor.create_message(
                conversation_id=conversation_id,
                content=rag_response_text,
                role="assistant",
                channel_type=channel_type,
                metadata={
                    "rag_used": True,
                    "input_tokens": rag_result["input_tokens"],
                    "output_tokens": rag_result["output_tokens"],
                }
            )
            logger.info(f"✅ AI message created: {ai_msg.id}")

            await notify_new_message(
                db=db,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=str(ai_msg.id)
            )
            logger.info(f"✅ Websocket broadcast sent for message {ai_msg.id}")
        except Exception as e:
            logger.error(f"❌ RAG response failed for {channel_type} conversation {conversation_id}: {e}", exc_info=True)
            # If message creation failed, don't send to Telegram
            if not ai_msg:
                rag_response_text = None

        if channel_type == "telegram" and telegram_context and rag_response_text:
            from app.services.telegram_sender import send_telegram_message
            sent = await send_telegram_message(
                bot_token=telegram_context["bot_token"],
                chat_id=telegram_context["chat_id"],
                text=rag_response_text,
            )
            if not sent:
                logger.error(
                    "Failed to deliver RAG reply to Telegram for conversation_id=%s chat_id=%s",
                    conversation_id,
                    telegram_context["chat_id"],
                )
        elif channel_type == "whatsapp" and whatsapp_context and rag_response_text:
            from app.services.whatsapp_sender import send_whatsapp_message
            sent = await send_whatsapp_message(
                access_token=whatsapp_context["access_token"],
                phone_number_id=whatsapp_context["phone_number_id"],
                to=whatsapp_context["recipient_phone"],
                text=rag_response_text,
            )
            if not sent:
                logger.error(
                    "Failed to deliver RAG reply to WhatsApp for conversation_id=%s", conversation_id
                )
        elif channel_type == "instagram" and instagram_context and rag_response_text:
            from app.services.instagram_sender import send_instagram_message
            sent = await send_instagram_message(
                access_token=instagram_context["access_token"],
                page_id=instagram_context["page_id"],
                recipient_id=instagram_context["recipient_id"],
                text=rag_response_text,
            )
            if not sent:
                logger.error(
                    "Failed to deliver RAG reply to Instagram for conversation_id=%s", conversation_id
                )


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

    if settings.TELEGRAM_SECRET_TOKEN:
        _verify_telegram_secret_token(
            request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""),
            settings.TELEGRAM_SECRET_TOKEN,
        )

    from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
    try:
        result = await WebhookHandlers(db).handle_telegram_webhook(payload, headers, bot_token)
    except WebhookProcessingError as e:
        if e.status_code == 200:
            return {"ok": True}  # permanent no-op — stop retries silently
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.error("Unexpected Telegram webhook error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal processing error")

    if result.get("status") == "success":
        external_msg_id = result["message_data"].get("external_message_id", "")
        if not await _claim_inbound_message("telegram", external_msg_id):
            logger.info("Telegram message %s already claimed — skipping", external_msg_id)
            return {"ok": True}

        # Extract chat_id from message_metadata (set by _extract_telegram_message)
        chat_id = result["message_data"].get("message_metadata", {}).get("chat_id")

        # Decrypt bot token for sending replies
        from app.services.encryption import decrypt_credential
        from app.models.channel import Channel
        from sqlalchemy import select as _select
        from app.utils.tasks import safe_create_task
        ch_result = await db.execute(
            _select(Channel).where(Channel.id == result["channel_id"])
        )
        ch = ch_result.scalar_one_or_none()
        decrypted_token = None
        if ch and ch.config and ch.config.get("bot_token"):
            decrypted_token = decrypt_credential(ch.config["bot_token"])

        telegram_context = None
        if chat_id and decrypted_token:
            telegram_context = {"bot_token": decrypted_token, "chat_id": chat_id}

        # Return 200 immediately — pipeline runs in background to meet Telegram's
        # 60-second webhook timeout and prevent duplicate-delivery retries.
        safe_create_task(
            _run_pipeline_with_own_session(
                workspace_id=str(result["workspace_id"]),
                channel_id=str(result["channel_id"]),
                message_data=result["message_data"],
                channel_type="telegram",
                telegram_context=telegram_context,
            ),
            name=f"pipeline.telegram.{external_msg_id}",
        )

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

    if settings.WHATSAPP_APP_SECRET:
        _verify_meta_signature(
            payload,
            request.headers.get("X-Hub-Signature-256", ""),
            settings.WHATSAPP_APP_SECRET,
        )

    from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
    try:
        result = await WebhookHandlers(db).handle_whatsapp_webhook(payload, headers, phone_number_id)
    except WebhookProcessingError as e:
        if e.status_code == 200:
            return {"status": "ok"}
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.error("Unexpected WhatsApp webhook error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal processing error")

    result_status = result.get("status")

    if result_status == "success":
        external_msg_id = result["message_data"].get("external_message_id", "")
        if not await _claim_inbound_message("whatsapp", external_msg_id):
            logger.info("WhatsApp message %s already claimed — skipping", external_msg_id)
            return {"status": "ok"}

        # Extract credentials so the pipeline can send replies back to the customer
        whatsapp_context = None
        try:
            from app.services.encryption import decrypt_credential
            from app.models.channel import Channel
            from sqlalchemy import select as _select
            ch_result = await db.execute(
                _select(Channel).where(Channel.id == result["channel_id"])
            )
            ch = ch_result.scalar_one_or_none()
            if ch and ch.config:
                access_token = decrypt_credential(ch.config.get("access_token", ""))
                wa_phone_number_id = decrypt_credential(ch.config.get("phone_number_id", ""))
                recipient_phone = result["message_data"].get("external_contact_id")
                if access_token and wa_phone_number_id and recipient_phone:
                    whatsapp_context = {
                        "access_token": access_token,
                        "phone_number_id": wa_phone_number_id,
                        "recipient_phone": recipient_phone,
                    }
        except Exception as e:
            logger.warning("Failed to extract WhatsApp channel credentials: %s", e)

        from app.utils.tasks import safe_create_task
        # Return 200 within Meta's 5-10 s window — pipeline runs in background.
        safe_create_task(
            _run_pipeline_with_own_session(
                workspace_id=str(result["workspace_id"]),
                channel_id=str(result["channel_id"]),
                message_data=result["message_data"],
                channel_type="whatsapp",
                whatsapp_context=whatsapp_context,
            ),
            name=f"pipeline.whatsapp.{external_msg_id}",
        )

    elif result_status == "status_update":
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
            logger.error("WhatsApp status update error: %s", e, exc_info=True)

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

    if settings.INSTAGRAM_APP_SECRET:
        _verify_meta_signature(
            payload,
            request.headers.get("X-Hub-Signature-256", ""),
            settings.INSTAGRAM_APP_SECRET,
        )

    from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
    try:
        result = await WebhookHandlers(db).handle_instagram_webhook(payload, headers, page_id)
    except WebhookProcessingError as e:
        if e.status_code == 200:
            return {"status": "ok"}
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.error("Unexpected Instagram webhook error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal processing error")

    if result.get("status") == "success":
        external_msg_id = result["message_data"].get("external_message_id", "")
        if not await _claim_inbound_message("instagram", external_msg_id):
            logger.info("Instagram message %s already claimed — skipping", external_msg_id)
            return {"status": "ok"}

        # Extract credentials so the pipeline can send replies back to the customer
        instagram_context = None
        try:
            from app.services.encryption import decrypt_credential
            from app.models.channel import Channel
            from sqlalchemy import select as _select
            ch_result = await db.execute(
                _select(Channel).where(Channel.id == result["channel_id"])
            )
            ch = ch_result.scalar_one_or_none()
            if ch and ch.config:
                access_token = decrypt_credential(ch.config.get("access_token", ""))
                ig_page_id = decrypt_credential(ch.config.get("page_id", ""))
                recipient_id = result["message_data"].get("external_contact_id")
                if access_token and ig_page_id and recipient_id:
                    instagram_context = {
                        "access_token": access_token,
                        "page_id": ig_page_id,
                        "recipient_id": recipient_id,
                    }
        except Exception as e:
            logger.warning("Failed to extract Instagram channel credentials: %s", e)

        from app.utils.tasks import safe_create_task
        # Return 200 within Meta's 5-10 s window — pipeline runs in background.
        safe_create_task(
            _run_pipeline_with_own_session(
                workspace_id=str(result["workspace_id"]),
                channel_id=str(result["channel_id"]),
                message_data=result["message_data"],
                channel_type="instagram",
                instagram_context=instagram_context,
            ),
            name=f"pipeline.instagram.{external_msg_id}",
        )

    return {"status": "ok"}
