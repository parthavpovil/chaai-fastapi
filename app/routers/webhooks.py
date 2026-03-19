"""
Webhook Handlers
Handles incoming webhooks from external services (Resend, etc.)
"""
from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional
import hmac
import hashlib
import json
from app.config import settings


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
