"""
Canned Responses Router
Saved reply templates for agents to speed up responses
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.models.canned_response import CannedResponse
from app.config import TIER_LIMITS


router = APIRouter(prefix="/api/canned-responses", tags=["canned-responses"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CannedResponseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=5000)
    shortcut: Optional[str] = Field(None, max_length=50)


class CannedResponseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    shortcut: Optional[str] = Field(None, max_length=50)


class CannedResponseOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    content: str
    shortcut: Optional[str]
    created_at: str
    updated_at: str


# ─── Helper ───────────────────────────────────────────────────────────────────

async def _check_canned_response_limit(db: AsyncSession, workspace: Workspace) -> None:
    tier = workspace.tier or "free"
    limit = TIER_LIMITS.get(tier, TIER_LIMITS["free"])["canned_responses"]
    if limit == -1:
        return  # unlimited

    count_result = await db.execute(
        select(func.count()).select_from(CannedResponse)
        .where(CannedResponse.workspace_id == workspace.id)
    )
    count = count_result.scalar_one()
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Canned response limit ({limit}) reached for your {tier} tier. Upgrade to create more."
        )


def _to_out(cr: CannedResponse) -> CannedResponseOut:
    return CannedResponseOut(
        id=str(cr.id),
        workspace_id=str(cr.workspace_id),
        name=cr.name,
        content=cr.content,
        shortcut=cr.shortcut,
        created_at=cr.created_at.isoformat(),
        updated_at=cr.updated_at.isoformat()
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=CannedResponseOut, status_code=201)
async def create_canned_response(
    request: CannedResponseCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create a canned response (workspace owner only)."""
    await _check_canned_response_limit(db, current_workspace)

    # Check shortcut uniqueness
    if request.shortcut:
        existing = await db.execute(
            select(CannedResponse)
            .where(CannedResponse.workspace_id == current_workspace.id)
            .where(CannedResponse.shortcut == request.shortcut)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Shortcut '{request.shortcut}' already exists")

    cr = CannedResponse(
        workspace_id=current_workspace.id,
        created_by=current_user.id,
        name=request.name,
        content=request.content,
        shortcut=request.shortcut
    )
    db.add(cr)
    await db.commit()
    await db.refresh(cr)
    return _to_out(cr)


@router.get("", response_model=List[CannedResponseOut])
async def list_canned_responses(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """List all canned responses for the workspace (agents + owners)."""
    result = await db.execute(
        select(CannedResponse)
        .where(CannedResponse.workspace_id == current_workspace.id)
        .order_by(CannedResponse.name.asc())
    )
    return [_to_out(cr) for cr in result.scalars().all()]


@router.put("/{canned_response_id}", response_model=CannedResponseOut)
async def update_canned_response(
    canned_response_id: str,
    request: CannedResponseUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Update a canned response (owner only)."""
    result = await db.execute(
        select(CannedResponse)
        .where(CannedResponse.id == UUID(canned_response_id))
        .where(CannedResponse.workspace_id == current_workspace.id)
    )
    cr = result.scalar_one_or_none()
    if not cr:
        raise HTTPException(status_code=404, detail="Canned response not found")

    if request.shortcut and request.shortcut != cr.shortcut:
        existing = await db.execute(
            select(CannedResponse)
            .where(CannedResponse.workspace_id == current_workspace.id)
            .where(CannedResponse.shortcut == request.shortcut)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Shortcut '{request.shortcut}' already exists")

    if request.name is not None:
        cr.name = request.name
    if request.content is not None:
        cr.content = request.content
    if request.shortcut is not None:
        cr.shortcut = request.shortcut

    await db.commit()
    await db.refresh(cr)
    return _to_out(cr)


@router.delete("/{canned_response_id}", status_code=204)
async def delete_canned_response(
    canned_response_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Delete a canned response (owner only)."""
    result = await db.execute(
        select(CannedResponse)
        .where(CannedResponse.id == UUID(canned_response_id))
        .where(CannedResponse.workspace_id == current_workspace.id)
    )
    cr = result.scalar_one_or_none()
    if not cr:
        raise HTTPException(status_code=404, detail="Canned response not found")

    await db.delete(cr)
    await db.commit()
