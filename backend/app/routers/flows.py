"""
Flow Router
CRUD + stats for interactive message flows
"""
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.middleware.auth_middleware import get_current_workspace
from app.models.flow import Flow, ConversationFlowState
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/flows", tags=["flows"])


class FlowCreate(BaseModel):
    name: str
    trigger_keywords: Optional[list] = None
    trigger_type: Optional[str] = "keyword"  # keyword | manual | ai_detected
    is_active: bool = True
    steps: dict


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    trigger_keywords: Optional[list] = None
    trigger_type: Optional[str] = None
    is_active: Optional[bool] = None
    steps: Optional[dict] = None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_flow(
    body: FlowCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    flow = Flow(
        workspace_id=str(workspace.id),
        name=body.name,
        trigger_keywords=body.trigger_keywords,
        trigger_type=body.trigger_type,
        is_active=body.is_active,
        steps=body.steps,
    )
    db.add(flow)
    await db.commit()
    await db.refresh(flow)
    return flow


@router.get("")
async def list_flows(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Flow)
        .where(Flow.workspace_id == str(workspace.id))
        .order_by(Flow.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{flow_id}")
async def get_flow(
    flow_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow_or_404(db, flow_id, workspace.id)
    return flow


@router.put("/{flow_id}")
async def update_flow(
    flow_id: UUID,
    body: FlowUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow_or_404(db, flow_id, workspace.id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(flow, field, value)
    flow.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(flow)
    return flow


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(
    flow_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow_or_404(db, flow_id, workspace.id)
    await db.delete(flow)
    await db.commit()


@router.post("/{flow_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_flow(
    flow_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    original = await _get_flow_or_404(db, flow_id, workspace.id)
    clone = Flow(
        workspace_id=str(workspace.id),
        name=f"{original.name} (copy)",
        trigger_keywords=original.trigger_keywords,
        trigger_type=original.trigger_type,
        is_active=False,  # start inactive
        steps=original.steps,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    return clone


@router.get("/{flow_id}/stats")
async def get_flow_stats(
    flow_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _get_flow_or_404(db, flow_id, workspace.id)

    total = await db.execute(
        select(func.count()).where(ConversationFlowState.flow_id == str(flow_id))
    )
    completed = await db.execute(
        select(func.count())
        .where(ConversationFlowState.flow_id == str(flow_id))
        .where(ConversationFlowState.completed_at.isnot(None))
    )
    abandoned = await db.execute(
        select(func.count())
        .where(ConversationFlowState.flow_id == str(flow_id))
        .where(ConversationFlowState.abandoned_at.isnot(None))
    )

    total_count = total.scalar() or 0
    completed_count = completed.scalar() or 0
    abandoned_count = abandoned.scalar() or 0

    return {
        "flow_id": str(flow_id),
        "total_started": total_count,
        "completed": completed_count,
        "abandoned": abandoned_count,
        "completion_rate": round(completed_count / total_count * 100, 1) if total_count else 0,
    }


async def _get_flow_or_404(db: AsyncSession, flow_id: UUID, workspace_id) -> Flow:
    result = await db.execute(
        select(Flow)
        .where(Flow.id == str(flow_id))
        .where(Flow.workspace_id == str(workspace_id))
    )
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow
