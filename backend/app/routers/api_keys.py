"""
API Keys Router
Programmatic access key management (Growth+ tier, owner only)
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.models.api_key import APIKey
from app.services.api_key_service import generate_api_key
from app.config import TIER_LIMITS


router = APIRouter(
    prefix="/api/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_permission("integrations.api_keys"))],
)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    expires_at: Optional[datetime] = None


class APIKeyCreatedResponse(BaseModel):
    """Returned only on creation — contains the raw key (shown once)."""
    id: str
    name: str
    prefix: str
    raw_key: str  # shown once
    expires_at: Optional[str]
    created_at: str


class APIKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    is_active: bool
    last_used_at: Optional[str]
    expires_at: Optional[str]
    created_at: str


# ─── Helper ───────────────────────────────────────────────────────────────────

def _require_feature(workspace: Workspace) -> None:
    if not TIER_LIMITS.get(workspace.tier or "free", {}).get("has_api_access", False):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="API key access requires Growth or Pro tier."
        )


def _to_out(key: APIKey) -> APIKeyOut:
    return APIKeyOut(
        id=str(key.id),
        name=key.name,
        prefix=key.prefix,
        is_active=key.is_active,
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        created_at=key.created_at.isoformat()
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    request: APIKeyCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create a new API key. The raw key is shown only once."""
    _require_feature(current_workspace)

    raw_key, prefix, key_hash = generate_api_key()

    key = APIKey(
        workspace_id=current_workspace.id,
        name=request.name,
        key_hash=key_hash,
        prefix=prefix,
        expires_at=request.expires_at
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return APIKeyCreatedResponse(
        id=str(key.id),
        name=key.name,
        prefix=key.prefix,
        raw_key=raw_key,
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        created_at=key.created_at.isoformat()
    )


@router.get("", response_model=List[APIKeyOut])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """List API keys (prefixes only — raw key is never returned after creation)."""
    _require_feature(current_workspace)

    result = await db.execute(
        select(APIKey)
        .where(APIKey.workspace_id == current_workspace.id)
        .order_by(APIKey.created_at.desc())
    )
    return [_to_out(k) for k in result.scalars().all()]


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Revoke (delete) an API key."""
    _require_feature(current_workspace)

    result = await db.execute(
        select(APIKey)
        .where(APIKey.id == UUID(key_id))
        .where(APIKey.workspace_id == current_workspace.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(key)
    await db.commit()
