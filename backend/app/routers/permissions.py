"""
GET /api/permissions — returns the effective permission map for the current user.

Accepts both owner JWT and agent JWT (and csk_* API keys treated as owner).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, security
from app.models.agent import Agent
from app.models.permission import WorkspacePermissionOverride
from app.models.workspace import Workspace
from app.models.user import User
from app.services import permission_service
from app.services.auth_service import auth_service

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


async def _resolve_workspace_and_role(
    current_user: User,
    credentials: HTTPAuthorizationCredentials,
    db: AsyncSession,
) -> tuple[Workspace, str]:
    """
    Resolve (workspace, role) from the current user + token.
    - Owner: workspace where owner_id == user.id
    - Agent: workspace via Agent join
    - API key csk_*: treated as owner
    """
    token = credentials.credentials

    # API keys are always treated as owner
    if token.startswith("csk_"):
        result = await db.execute(
            select(Workspace).where(Workspace.owner_id == current_user.id)
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace, "owner"

    payload = auth_service.decode_access_token(token)
    role = (payload or {}).get("role", "owner")

    if role == "agent":
        result = await db.execute(
            select(Agent, Workspace)
            .join(Workspace)
            .where(Agent.user_id == current_user.id, Agent.is_active == True)
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active agent profile found")
        return row.Workspace, "agent"

    # owner
    result = await db.execute(
        select(Workspace).where(Workspace.owner_id == current_user.id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace, "owner"


@router.get("")
async def get_permissions(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the effective permission map for the authenticated user.

    - Owners receive the full workspace permission map (tier + overrides).
    - Agents receive the same map masked by the agent role ceiling.
    """
    workspace, role = await _resolve_workspace_and_role(current_user, credentials, db)

    flat = await permission_service.get_effective_permissions(workspace, role, db)
    nested = permission_service.build_nested_response(flat)

    # Load override row for meta fields
    override_row = await permission_service.get_override_row(workspace.id, db)
    permissions_version = override_row.permissions_version if override_row else 1
    updated_at = (
        override_row.updated_at.isoformat()
        if override_row and override_row.updated_at
        else None
    )

    return {
        "permissions": nested,
        "meta": {
            "workspace_id": str(workspace.id),
            "tier": workspace.tier or "free",
            "role": role,
            "permissions_version": permissions_version,
            "updated_at": updated_at,
        },
    }
