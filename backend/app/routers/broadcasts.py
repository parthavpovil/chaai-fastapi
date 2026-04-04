"""
Broadcasts Router
Create, schedule, send, and monitor WhatsApp broadcast campaigns
"""
from typing import Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.middleware.auth_middleware import get_current_workspace, require_permission
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.workspace import Workspace
from app.tasks.broadcast_tasks import enqueue_broadcast

router = APIRouter(
    prefix="/api/broadcasts",
    tags=["broadcasts"],
    dependencies=[Depends(require_permission("automation.broadcasts"))],
)


class BroadcastCreate(BaseModel):
    name: str
    template_id: str
    variable_mapping: Optional[dict] = None
    audience_type: str   # all | tag | manual
    audience_filter: Optional[dict] = None
    scheduled_at: Optional[datetime] = None


class BroadcastUpdate(BaseModel):
    name: Optional[str] = None
    template_id: Optional[str] = None
    variable_mapping: Optional[dict] = None
    audience_type: Optional[str] = None
    audience_filter: Optional[dict] = None
    scheduled_at: Optional[datetime] = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_broadcast(
    body: BroadcastCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    broadcast = Broadcast(
        workspace_id=str(workspace.id),
        name=body.name,
        template_id=body.template_id,
        variable_mapping=body.variable_mapping,
        audience_type=body.audience_type,
        audience_filter=body.audience_filter,
        scheduled_at=body.scheduled_at,
    )
    db.add(broadcast)
    await db.commit()
    await db.refresh(broadcast)
    return broadcast


@router.get("")
async def list_broadcasts(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast)
        .where(Broadcast.workspace_id == str(workspace.id))
        .order_by(Broadcast.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{broadcast_id}")
async def get_broadcast(
    broadcast_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    return await _get_broadcast_or_404(db, broadcast_id, workspace.id)


@router.put("/{broadcast_id}")
async def update_broadcast(
    broadcast_id: UUID,
    body: BroadcastUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    broadcast = await _get_broadcast_or_404(db, broadcast_id, workspace.id)
    if broadcast.status not in ("draft",):
        raise HTTPException(status_code=400, detail="Only draft broadcasts can be edited")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(broadcast, field, value)
    await db.commit()
    await db.refresh(broadcast)
    return broadcast


@router.post("/{broadcast_id}/send")
async def send_broadcast(
    broadcast_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    broadcast = await _get_broadcast_or_404(db, broadcast_id, workspace.id)
    if broadcast.status not in ("draft",):
        raise HTTPException(status_code=400, detail="Broadcast is not in draft state")

    await enqueue_broadcast(
        broadcast_id=str(broadcast_id),
        workspace_id=str(workspace.id),
        run_at=broadcast.scheduled_at,
    )
    broadcast.status = "scheduled" if broadcast.scheduled_at else "queued"
    await db.commit()
    return {"status": broadcast.status}


@router.post("/{broadcast_id}/cancel")
async def cancel_broadcast(
    broadcast_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    broadcast = await _get_broadcast_or_404(db, broadcast_id, workspace.id)
    if broadcast.status in ("sent", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a broadcast with status '{broadcast.status}'")
    broadcast.status = "cancelled"
    await db.commit()
    return {"status": "cancelled"}


@router.get("/{broadcast_id}/stats")
async def get_broadcast_stats(
    broadcast_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    broadcast = await _get_broadcast_or_404(db, broadcast_id, workspace.id)

    counts_result = await db.execute(
        select(BroadcastRecipient.status, func.count().label("count"))
        .where(BroadcastRecipient.broadcast_id == str(broadcast_id))
        .group_by(BroadcastRecipient.status)
    )
    counts = {row.status: row.count for row in counts_result}

    total = sum(counts.values())
    return {
        "broadcast_id": str(broadcast_id),
        "status": broadcast.status,
        "total": total,
        "sent": counts.get("sent", 0),
        "delivered": counts.get("delivered", 0),
        "read": counts.get("read", 0),
        "failed": counts.get("failed", 0),
        "delivery_rate": round(counts.get("delivered", 0) / total * 100, 1) if total else 0,
        "read_rate": round(counts.get("read", 0) / total * 100, 1) if total else 0,
    }


@router.get("/{broadcast_id}/recipients")
async def get_broadcast_recipients(
    broadcast_id: UUID,
    limit: int = 50,
    offset: int = 0,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _get_broadcast_or_404(db, broadcast_id, workspace.id)

    result = await db.execute(
        select(BroadcastRecipient)
        .where(BroadcastRecipient.broadcast_id == str(broadcast_id))
        .order_by(BroadcastRecipient.sent_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def _get_broadcast_or_404(db: AsyncSession, broadcast_id: UUID, workspace_id) -> Broadcast:
    result = await db.execute(
        select(Broadcast)
        .where(Broadcast.id == str(broadcast_id))
        .where(Broadcast.workspace_id == str(workspace_id))
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    return broadcast
