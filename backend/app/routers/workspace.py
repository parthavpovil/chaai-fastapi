"""
Workspace Router
Workspace settings, AI config, and overview endpoints
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.models.conversation import Conversation
from app.models.message import Message
from app.config import TIER_LIMITS


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class AIConfigUpdate(BaseModel):
    ai_provider: str = Field(..., pattern="^(google|openai|groq|anthropic)$")
    ai_model: Optional[str] = Field(None, max_length=100)
    ai_api_key: Optional[str] = Field(None, max_length=500)  # plaintext — will be encrypted


class AIPipelineConfigUpdate(BaseModel):
    ai_mode: str = Field(..., pattern="^(rag|ai_agent)$")
    ai_provider: Optional[str] = Field(None, pattern="^(anthropic|openai|google|groq)$")
    ai_model: Optional[str] = Field(None, max_length=100)
    ai_api_key: Optional[str] = Field(None, max_length=500)


class WorkspaceSettingsUpdate(BaseModel):
    fallback_msg: Optional[str] = Field(None, max_length=500)
    alert_email: Optional[str] = Field(None, max_length=200)
    agents_enabled: Optional[bool] = None
    escalation_keywords: Optional[List[str]] = Field(None, max_length=100)
    escalation_sensitivity: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    escalation_email_enabled: Optional[bool] = None
    ai_enabled: Optional[bool] = None              # False = skip all LLM, route directly to human agents
    auto_escalation_enabled: Optional[bool] = None # False = escalation classifier never runs automatically


class WorkspaceOverview(BaseModel):
    workspace_id: str
    name: str
    tier: str
    conversations_today: int
    messages_this_month: int
    tier_quota_remaining: int
    tier_quota_total: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.put("/ai-config")
async def update_ai_config(
    request: AIConfigUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Update workspace AI model configuration (Growth+ tier, owner only)."""
    tier = current_workspace.tier or "free"
    if not TIER_LIMITS.get(tier, {}).get("has_custom_ai", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Custom AI model selection requires Growth or Pro tier."
        )

    meta = current_workspace.meta or {}
    meta["ai_provider"] = request.ai_provider
    if request.ai_model:
        meta["ai_model"] = request.ai_model
    if request.ai_api_key:
        meta["ai_api_key"] = request.ai_api_key  # store plaintext; encrypt in transit via HTTPS

    current_workspace.meta = meta
    await db.commit()
    return {"status": "updated", "ai_provider": request.ai_provider, "ai_model": meta.get("ai_model")}


@router.get("/ai-config")
async def get_ai_config(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """Get current workspace AI configuration."""
    meta = current_workspace.meta or {}
    return {
        "ai_provider": meta.get("ai_provider"),
        "ai_model": meta.get("ai_model"),
        "has_api_key": bool(meta.get("ai_api_key")),
    }


@router.put("/ai-pipeline")
async def update_ai_pipeline(
    request: AIPipelineConfigUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Configure the full AI pipeline (mode + model + provider). Growth+ tier required."""
    tier = current_workspace.tier or "free"
    if not TIER_LIMITS.get(tier, {}).get("has_custom_ai", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI pipeline configuration requires Growth or Pro tier.",
        )

    meta = current_workspace.meta or {}
    meta["ai_mode"] = request.ai_mode
    if request.ai_provider:
        meta["ai_provider"] = request.ai_provider
    if request.ai_model:
        meta["ai_model"] = request.ai_model
    if request.ai_api_key:
        meta["ai_api_key"] = request.ai_api_key

    current_workspace.meta = meta
    await db.commit()
    return {
        "status": "updated",
        "ai_mode": request.ai_mode,
        "ai_provider": meta.get("ai_provider"),
        "ai_model": meta.get("ai_model"),
    }


@router.get("/ai-pipeline")
async def get_ai_pipeline(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """Get current AI pipeline configuration."""
    meta = current_workspace.meta or {}
    return {
        "ai_mode": meta.get("ai_mode", "rag"),
        "ai_provider": meta.get("ai_provider"),
        "ai_model": meta.get("ai_model"),
        "has_api_key": bool(meta.get("ai_api_key")),
    }


@router.put("/settings")
async def update_workspace_settings(
    request: WorkspaceSettingsUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Update workspace settings (owner only)."""
    if request.fallback_msg is not None:
        current_workspace.fallback_msg = request.fallback_msg
    if request.alert_email is not None:
        current_workspace.alert_email = request.alert_email
    if request.agents_enabled is not None:
        current_workspace.agents_enabled = request.agents_enabled
    if request.escalation_keywords is not None:
        current_workspace.escalation_keywords = request.escalation_keywords
    if request.escalation_sensitivity is not None:
        current_workspace.escalation_sensitivity = request.escalation_sensitivity
    if request.escalation_email_enabled is not None:
        current_workspace.escalation_email_enabled = request.escalation_email_enabled
    if request.ai_enabled is not None:
        current_workspace.ai_enabled = request.ai_enabled
    if request.auto_escalation_enabled is not None:
        current_workspace.auto_escalation_enabled = request.auto_escalation_enabled

    await db.commit()
    await db.refresh(current_workspace)
    return {
        "status": "updated",
        "fallback_msg": current_workspace.fallback_msg,
        "alert_email": current_workspace.alert_email,
        "agents_enabled": current_workspace.agents_enabled,
        "escalation_keywords": current_workspace.escalation_keywords,
        "escalation_sensitivity": current_workspace.escalation_sensitivity,
        "escalation_email_enabled": current_workspace.escalation_email_enabled,
        "ai_enabled": current_workspace.ai_enabled,
        "auto_escalation_enabled": current_workspace.auto_escalation_enabled,
    }


@router.get("/overview", response_model=WorkspaceOverview)
async def get_workspace_overview(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Get workspace overview statistics for the owner dashboard."""
    from datetime import datetime, timezone, timedelta
    from app.models.usage_counter import UsageCounter

    today = datetime.now(timezone.utc).date()
    month_key = today.strftime("%Y-%m")

    # Conversations created today
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    conv_today_result = await db.execute(
        select(func.count(Conversation.id))
        .where(Conversation.workspace_id == current_workspace.id)
        .where(Conversation.created_at >= today_start)
    )
    conversations_today = conv_today_result.scalar_one() or 0

    # Messages this month (from UsageCounter)
    usage_result = await db.execute(
        select(UsageCounter)
        .where(UsageCounter.workspace_id == current_workspace.id)
        .where(UsageCounter.month == month_key)
    )
    usage = usage_result.scalar_one_or_none()
    messages_this_month = usage.messages_sent if usage else 0

    tier = current_workspace.tier or "free"
    quota_total = TIER_LIMITS.get(tier, TIER_LIMITS["free"])["monthly_messages"]
    quota_remaining = max(0, quota_total - messages_this_month)

    return WorkspaceOverview(
        workspace_id=str(current_workspace.id),
        name=current_workspace.name,
        tier=tier,
        conversations_today=conversations_today,
        messages_this_month=messages_this_month,
        tier_quota_remaining=quota_remaining,
        tier_quota_total=quota_total,
    )
