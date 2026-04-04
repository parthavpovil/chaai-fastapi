"""
Super admin permission management routes.

  GET  /api/admin/permissions/tiers                        — list tier templates
  GET  /api/admin/permissions/tiers/{tier_id}              — get full flags for a tier
  PUT  /api/admin/permissions/tiers/{tier_id}              — replace tier flags
  GET  /api/admin/permissions/workspaces/{workspace_id}    — effective map + override state
  PATCH /api/admin/permissions/workspaces/{workspace_id}   — set allow/deny/inherit per key

All routes require super admin access (email == SUPER_ADMIN_EMAIL).
"""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import get_current_user
from app.models.permission import TierPermissionTemplate, WorkspacePermissionOverride
from app.models.user import User
from app.models.workspace import Workspace
from app.services import permission_service

router = APIRouter(prefix="/api/admin/permissions", tags=["admin-permissions"])


# ---------------------------------------------------------------------------
# Super admin guard (replicates the pattern from app/routers/admin.py)
# ---------------------------------------------------------------------------

def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    from app.config import settings
    if current_user.email.lower() != settings.SUPER_ADMIN_EMAIL.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TierTemplateSummary(BaseModel):
    tier_id: str
    updated_at: str | None


class TierTemplateDetail(BaseModel):
    tier_id: str
    flags: dict[str, bool]
    updated_at: str | None
    updated_by_user_id: str | None


class WorkspacePermissionView(BaseModel):
    workspace_id: str
    tier: str
    permissions_version: int
    effective: dict[str, dict[str, bool]]
    overrides: dict[str, str]  # key → "allow" | "deny"


class OverridePatchRequest(BaseModel):
    # dot-notation key → "allow" | "deny" | "inherit"
    overrides: dict[str, str]


# ---------------------------------------------------------------------------
# Tier template endpoints
# ---------------------------------------------------------------------------

@router.get("/tiers", response_model=list[TierTemplateSummary])
async def list_tiers(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all tier template IDs with their last-updated timestamp."""
    result = await db.execute(select(TierPermissionTemplate))
    rows = result.scalars().all()
    return [
        TierTemplateSummary(
            tier_id=row.tier_id,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )
        for row in rows
    ]


@router.get("/tiers/{tier_id}", response_model=TierTemplateDetail)
async def get_tier(
    tier_id: str,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get the full flags map for a specific tier template."""
    result = await db.execute(
        select(TierPermissionTemplate).where(TierPermissionTemplate.tier_id == tier_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Tier template '{tier_id}' not found")
    return TierTemplateDetail(
        tier_id=row.tier_id,
        flags=row.flags or {},
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        updated_by_user_id=str(row.updated_by_user_id) if row.updated_by_user_id else None,
    )


@router.put("/tiers/{tier_id}", response_model=TierTemplateDetail)
async def update_tier(
    tier_id: str,
    body: dict[str, bool],
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Replace the full flags map for a tier template.
    Validates that all supplied keys are in the permission registry.
    """
    unknown = set(body.keys()) - set(permission_service.PERMISSION_REGISTRY)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown permission keys: {sorted(unknown)}",
        )

    result = await db.execute(
        select(TierPermissionTemplate).where(TierPermissionTemplate.tier_id == tier_id)
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None:
        row = TierPermissionTemplate(
            tier_id=tier_id,
            flags=body,
            updated_at=now,
            updated_by_user_id=current_user.id,
        )
        db.add(row)
    else:
        row.flags = body
        row.updated_at = now
        row.updated_by_user_id = current_user.id

    await db.commit()
    await db.refresh(row)

    return TierTemplateDetail(
        tier_id=row.tier_id,
        flags=row.flags or {},
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        updated_by_user_id=str(row.updated_by_user_id) if row.updated_by_user_id else None,
    )


# ---------------------------------------------------------------------------
# Workspace override endpoints
# ---------------------------------------------------------------------------

@router.get("/workspaces/{workspace_id}", response_model=WorkspacePermissionView)
async def get_workspace_permissions(
    workspace_id: UUID,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the effective permission map + per-key override state for a workspace."""
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    flat = await permission_service.get_effective_permissions(workspace, "owner", db)
    nested = permission_service.build_nested_response(flat)

    override_row = await permission_service.get_override_row(workspace_id, db)
    overrides = dict(override_row.overrides) if override_row else {}
    version = override_row.permissions_version if override_row else 1

    return WorkspacePermissionView(
        workspace_id=str(workspace_id),
        tier=workspace.tier or "free",
        permissions_version=version,
        effective=nested,
        overrides=overrides,
    )


@router.patch("/workspaces/{workspace_id}", response_model=WorkspacePermissionView)
async def patch_workspace_permissions(
    workspace_id: UUID,
    body: OverridePatchRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Set allow / deny / inherit for specific permission keys on a workspace.
    - "allow"   → force True regardless of tier
    - "deny"    → force False regardless of tier
    - "inherit" → remove override, revert to tier default
    """
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Validate keys and values
    valid_values = {"allow", "deny", "inherit"}
    unknown_keys = set(body.overrides.keys()) - set(permission_service.PERMISSION_REGISTRY)
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown permission keys: {sorted(unknown_keys)}",
        )
    bad_values = {v for v in body.overrides.values() if v not in valid_values}
    if bad_values:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid override values: {sorted(bad_values)}. Must be allow, deny, or inherit.",
        )

    row = await permission_service.upsert_overrides(
        workspace_id, body.overrides, current_user.id, db
    )

    flat = await permission_service.get_effective_permissions(workspace, "owner", db)
    nested = permission_service.build_nested_response(flat)

    return WorkspacePermissionView(
        workspace_id=str(workspace_id),
        tier=workspace.tier or "free",
        permissions_version=row.permissions_version,
        effective=nested,
        overrides=dict(row.overrides or {}),
    )
