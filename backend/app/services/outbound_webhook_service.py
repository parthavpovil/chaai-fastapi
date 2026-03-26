"""
Outbound Webhook Service
Signs and delivers HTTP POST events to registered workspace webhook URLs
"""
import hmac
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

MAX_FAILURES_BEFORE_DISABLE = 5
MAX_RESPONSE_BODY_LEN = 2000


async def trigger_event(
    workspace_id: str,
    event_type: str,
    payload: Dict[str, Any],
    db: AsyncSession = None,  # kept for backward compat, ignored
) -> None:
    """
    Find all active outbound webhooks subscribed to event_type and POST to them.
    Opens its own DB session so it can safely run as an asyncio.create_task.
    Silently handles errors — never raises to callers.
    """
    from app.database import AsyncSessionLocal
    from app.models.outbound_webhook import OutboundWebhook

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OutboundWebhook)
                .where(OutboundWebhook.workspace_id == UUID(workspace_id))
                .where(OutboundWebhook.is_active == True)
            )
            webhooks = result.scalars().all()

            for wh in webhooks:
                subscribed = wh.events or []
                if event_type not in subscribed:
                    continue

                await _deliver(session, wh, event_type, payload)

    except Exception as e:
        logger.error(f"outbound_webhook trigger_event error: {e}")


async def _deliver(db: AsyncSession, webhook, event_type: str, payload: Dict[str, Any]) -> None:
    """Attempt delivery to a single webhook URL and write a delivery log entry."""
    from app.models.outbound_webhook_log import OutboundWebhookLog

    response_status_code = None
    response_body = None
    is_success = False
    start = time.monotonic()

    try:
        import httpx

        body = json.dumps(payload, default=str).encode()
        signature = _sign(webhook.secret, body)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                webhook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-ChatSaaS-Signature": f"sha256={signature}",
                    "X-Event-Type": event_type,
                }
            )

        response_status_code = resp.status_code
        response_body = resp.text[:MAX_RESPONSE_BODY_LEN]
        is_success = resp.is_success

        if is_success:
            webhook.failure_count = 0
            webhook.last_triggered_at = datetime.now(timezone.utc)
        else:
            await _record_failure(db, webhook)

    except Exception as e:
        logger.warning(f"Webhook delivery failed for {webhook.url}: {e}")
        response_body = str(e)[:MAX_RESPONSE_BODY_LEN]
        await _record_failure(db, webhook)

    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_entry = OutboundWebhookLog(
            webhook_id=webhook.id,
            workspace_id=webhook.workspace_id,
            event_type=event_type,
            payload=payload,
            response_status_code=response_status_code,
            response_body=response_body,
            duration_ms=duration_ms,
            is_success=is_success,
        )
        db.add(log_entry)

    await db.commit()


async def _get_workspace_owner_email(db: AsyncSession, workspace_id) -> str | None:
    """Return the email of the workspace owner, or None if not found."""
    from app.models.user import User
    from app.models.workspace import Workspace
    result = await db.execute(
        select(User.email)
        .join(Workspace, Workspace.owner_id == User.id)
        .where(Workspace.id == workspace_id)
    )
    return result.scalar_one_or_none()


async def _record_failure(db: AsyncSession, webhook) -> None:
    webhook.failure_count = (webhook.failure_count or 0) + 1
    if webhook.failure_count >= MAX_FAILURES_BEFORE_DISABLE:
        webhook.is_active = False
        logger.warning(
            "Outbound webhook %s disabled after %d consecutive failures",
            webhook.id,
            webhook.failure_count,
        )
        # Notify workspace owner by email
        try:
            from app.services.email_service import EmailService
            email_svc = EmailService()
            owner_email = await _get_workspace_owner_email(db, webhook.workspace_id)
            if owner_email:
                await email_svc.send_email(
                    to=owner_email,
                    subject="Outbound Webhook Auto-Disabled",
                    body=(
                        f"Your outbound webhook has been automatically disabled "
                        f"after {webhook.failure_count} consecutive delivery failures.\n\n"
                        f"URL: {webhook.url}\n\n"
                        f"Please check that your endpoint is reachable and re-enable "
                        f"the webhook from your workspace settings once the issue is resolved."
                    ),
                )
        except Exception:
            logger.warning("Failed to send webhook-disabled notification email", exc_info=True)


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
