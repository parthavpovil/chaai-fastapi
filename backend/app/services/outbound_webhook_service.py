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
    db: AsyncSession,
    workspace_id: str,
    event_type: str,
    payload: Dict[str, Any]
) -> None:
    """
    Find all active outbound webhooks subscribed to event_type and POST to them.
    Silently handles errors — never raises to callers.
    """
    try:
        from app.models.outbound_webhook import OutboundWebhook

        result = await db.execute(
            select(OutboundWebhook)
            .where(OutboundWebhook.workspace_id == UUID(workspace_id))
            .where(OutboundWebhook.is_active == True)
        )
        webhooks = result.scalars().all()

        for wh in webhooks:
            subscribed = wh.events or []
            if event_type not in subscribed:
                continue

            await _deliver(db, wh, event_type, payload)

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


async def _record_failure(db: AsyncSession, webhook) -> None:
    webhook.failure_count = (webhook.failure_count or 0) + 1
    if webhook.failure_count >= MAX_FAILURES_BEFORE_DISABLE:
        webhook.is_active = False
        logger.warning(f"Outbound webhook {webhook.id} disabled after {webhook.failure_count} failures")


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
