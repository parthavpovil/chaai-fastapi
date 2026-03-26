"""
Outbound Webhooks Router
Workspace event subscriptions (Growth+ tier, owner only)
"""
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, HttpUrl

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.models.outbound_webhook import OutboundWebhook
from app.models.outbound_webhook_log import OutboundWebhookLog
from app.config import TIER_LIMITS


VALID_EVENTS = {
    "conversation.created",
    "conversation.escalated",
    "conversation.resolved",
    "message.received",
    "contact.updated",
    "csat.submitted",
}

router = APIRouter(prefix="/api/webhooks/outbound", tags=["outbound-webhooks"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class OutboundWebhookCreate(BaseModel):
    url: str = Field(..., max_length=500)
    events: List[str] = Field(..., min_length=1)


class OutboundWebhookUpdate(BaseModel):
    url: Optional[str] = Field(None, max_length=500)
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None


class OutboundWebhookOut(BaseModel):
    id: str
    url: str
    events: List[str]
    is_active: bool
    failure_count: int
    last_triggered_at: Optional[str]
    created_at: str


# ─── Helper ───────────────────────────────────────────────────────────────────

def _require_feature(workspace: Workspace) -> None:
    if not TIER_LIMITS.get(workspace.tier or "free", {}).get("has_outbound_webhooks", False):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Outbound webhooks require Growth or Pro tier."
        )


def _validate_events(events: List[str]) -> None:
    invalid = set(events) - VALID_EVENTS
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event types: {', '.join(sorted(invalid))}. Valid: {', '.join(sorted(VALID_EVENTS))}"
        )


def _to_out(wh: OutboundWebhook) -> OutboundWebhookOut:
    return OutboundWebhookOut(
        id=str(wh.id),
        url=wh.url,
        events=wh.events or [],
        is_active=wh.is_active,
        failure_count=wh.failure_count or 0,
        last_triggered_at=wh.last_triggered_at.isoformat() if wh.last_triggered_at else None,
        created_at=wh.created_at.isoformat()
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=OutboundWebhookOut, status_code=201)
async def create_outbound_webhook(
    request: OutboundWebhookCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Register an outbound webhook (Growth+ tier)."""
    _require_feature(current_workspace)
    _validate_events(request.events)

    wh = OutboundWebhook(
        workspace_id=current_workspace.id,
        url=request.url,
        events=request.events,
        secret=secrets.token_hex(32),
    )
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    return _to_out(wh)


@router.get("", response_model=List[OutboundWebhookOut])
async def list_outbound_webhooks(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """List registered outbound webhooks."""
    _require_feature(current_workspace)

    result = await db.execute(
        select(OutboundWebhook)
        .where(OutboundWebhook.workspace_id == current_workspace.id)
        .order_by(OutboundWebhook.created_at.desc())
    )
    return [_to_out(wh) for wh in result.scalars().all()]


@router.put("/{webhook_id}", response_model=OutboundWebhookOut)
async def update_outbound_webhook(
    webhook_id: str,
    request: OutboundWebhookUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Update an outbound webhook."""
    _require_feature(current_workspace)

    result = await db.execute(
        select(OutboundWebhook)
        .where(OutboundWebhook.id == UUID(webhook_id))
        .where(OutboundWebhook.workspace_id == current_workspace.id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    if request.url is not None:
        wh.url = request.url
    if request.events is not None:
        _validate_events(request.events)
        wh.events = request.events
    if request.is_active is not None:
        wh.is_active = request.is_active
        if request.is_active:
            wh.failure_count = 0  # reset on re-enable

    await db.commit()
    await db.refresh(wh)
    return _to_out(wh)


# ─── Delivery Log Schemas ─────────────────────────────────────────────────────

class WebhookLogOut(BaseModel):
    id: str
    event_type: str
    payload: dict
    response_status_code: Optional[int]
    response_body: Optional[str]
    duration_ms: Optional[int]
    is_success: bool
    delivered_at: str


class WebhookLogListResponse(BaseModel):
    logs: List[WebhookLogOut]
    total_count: int
    has_more: bool


# ─── Delivery Log Endpoints ────────────────────────────────────────────────────

@router.get("/{webhook_id}/logs", response_model=WebhookLogListResponse)
async def list_webhook_logs(
    webhook_id: str,
    success: Optional[bool] = Query(None, description="Filter by success/failure"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """List delivery logs for a webhook (Growth+ tier, last 30 days)."""
    _require_feature(current_workspace)

    wh_result = await db.execute(
        select(OutboundWebhook)
        .where(OutboundWebhook.id == UUID(webhook_id))
        .where(OutboundWebhook.workspace_id == current_workspace.id)
    )
    if not wh_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Webhook not found")

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    query = (
        select(OutboundWebhookLog)
        .where(OutboundWebhookLog.webhook_id == UUID(webhook_id))
        .where(OutboundWebhookLog.delivered_at >= cutoff)
    )
    if success is not None:
        query = query.where(OutboundWebhookLog.is_success == success)

    count_result = await db.execute(
        select(OutboundWebhookLog.id)
        .where(OutboundWebhookLog.webhook_id == UUID(webhook_id))
        .where(OutboundWebhookLog.delivered_at >= cutoff)
        .where(True if success is None else OutboundWebhookLog.is_success == success)
    )
    total_count = len(count_result.all())

    query = query.order_by(OutboundWebhookLog.delivered_at.desc()).limit(limit + 1).offset(offset)
    result = await db.execute(query)
    logs = result.scalars().all()
    has_more = len(logs) > limit
    logs = logs[:limit]

    return WebhookLogListResponse(
        logs=[_log_to_out(lg) for lg in logs],
        total_count=total_count,
        has_more=has_more,
    )


@router.get("/{webhook_id}/logs/{log_id}", response_model=WebhookLogOut)
async def get_webhook_log(
    webhook_id: str,
    log_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Get a single delivery log entry."""
    _require_feature(current_workspace)

    result = await db.execute(
        select(OutboundWebhookLog)
        .where(OutboundWebhookLog.id == UUID(log_id))
        .where(OutboundWebhookLog.webhook_id == UUID(webhook_id))
        .where(OutboundWebhookLog.workspace_id == current_workspace.id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return _log_to_out(log)


def _log_to_out(log: OutboundWebhookLog) -> WebhookLogOut:
    return WebhookLogOut(
        id=str(log.id),
        event_type=log.event_type,
        payload=log.payload or {},
        response_status_code=log.response_status_code,
        response_body=log.response_body,
        duration_ms=log.duration_ms,
        is_success=log.is_success,
        delivered_at=log.delivered_at.isoformat(),
    )


@router.delete("/{webhook_id}", status_code=204)
async def delete_outbound_webhook(
    webhook_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Delete an outbound webhook."""
    _require_feature(current_workspace)

    result = await db.execute(
        select(OutboundWebhook)
        .where(OutboundWebhook.id == UUID(webhook_id))
        .where(OutboundWebhook.workspace_id == current_workspace.id)
    )
    wh = result.scalar_one_or_none()
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await db.delete(wh)
    await db.commit()
