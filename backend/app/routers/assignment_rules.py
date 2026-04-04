"""
Assignment Rules Router
Automatic conversation routing rules (Pro tier only)
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.models.assignment_rule import AssignmentRule


router = APIRouter(
    prefix="/api/assignment-rules",
    tags=["assignment-rules"],
    dependencies=[Depends(require_permission("productivity.assignment_rules"))],
)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class AssignmentRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    priority: int = Field(100, ge=1, le=1000)
    conditions: dict = Field(default_factory=dict)
    action: str = Field(..., pattern="^(round_robin|specific_agent|least_loaded)$")
    target_agent_id: Optional[str] = None
    is_active: bool = True


class AssignmentRuleUpdate(BaseModel):
    name: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=1000)
    conditions: Optional[dict] = None
    action: Optional[str] = Field(None, pattern="^(round_robin|specific_agent|least_loaded)$")
    target_agent_id: Optional[str] = None
    is_active: Optional[bool] = None


class AssignmentRuleOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    priority: int
    conditions: dict
    action: str
    target_agent_id: Optional[str]
    is_active: bool
    created_at: str


# ─── Helper ───────────────────────────────────────────────────────────────────

def _to_out(rule: AssignmentRule) -> AssignmentRuleOut:
    return AssignmentRuleOut(
        id=str(rule.id),
        workspace_id=str(rule.workspace_id),
        name=rule.name,
        priority=rule.priority,
        conditions=rule.conditions or {},
        action=rule.action,
        target_agent_id=str(rule.target_agent_id) if rule.target_agent_id else None,
        is_active=rule.is_active,
        created_at=rule.created_at.isoformat()
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=AssignmentRuleOut, status_code=201)
async def create_rule(
    request: AssignmentRuleCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create an assignment rule (Pro tier, owner only)."""
    target = UUID(request.target_agent_id) if request.target_agent_id else None
    rule = AssignmentRule(
        workspace_id=current_workspace.id,
        name=request.name,
        priority=request.priority,
        conditions=request.conditions,
        action=request.action,
        target_agent_id=target,
        is_active=request.is_active
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _to_out(rule)


@router.get("", response_model=List[AssignmentRuleOut])
async def list_rules(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """List assignment rules (Pro tier, owner only)."""
    result = await db.execute(
        select(AssignmentRule)
        .where(AssignmentRule.workspace_id == current_workspace.id)
        .order_by(AssignmentRule.priority.asc())
    )
    return [_to_out(r) for r in result.scalars().all()]


@router.put("/{rule_id}", response_model=AssignmentRuleOut)
async def update_rule(
    rule_id: str,
    request: AssignmentRuleUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Update an assignment rule (Pro tier, owner only)."""
    result = await db.execute(
        select(AssignmentRule)
        .where(AssignmentRule.id == UUID(rule_id))
        .where(AssignmentRule.workspace_id == current_workspace.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Assignment rule not found")

    if request.name is not None:
        rule.name = request.name
    if request.priority is not None:
        rule.priority = request.priority
    if request.conditions is not None:
        rule.conditions = request.conditions
    if request.action is not None:
        rule.action = request.action
    if request.target_agent_id is not None:
        rule.target_agent_id = UUID(request.target_agent_id)
    if request.is_active is not None:
        rule.is_active = request.is_active

    await db.commit()
    await db.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Delete an assignment rule (Pro tier, owner only)."""
    result = await db.execute(
        select(AssignmentRule)
        .where(AssignmentRule.id == UUID(rule_id))
        .where(AssignmentRule.workspace_id == current_workspace.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Assignment rule not found")

    await db.delete(rule)
    await db.commit()
