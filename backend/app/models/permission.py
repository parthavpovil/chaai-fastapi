"""
Permission models for tier templates and workspace overrides.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class TierPermissionTemplate(Base):
    """
    Stores the default permission flags for each billing tier.
    Super admin manages these rows. Workspaces inherit from their tier's row.
    """
    __tablename__ = "tier_permission_templates"

    tier_id = Column(String, primary_key=True)  # "free" | "starter" | "growth" | "pro"
    flags = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_by_user_id = Column(UUID(as_uuid=True), nullable=True)


class WorkspacePermissionOverride(Base):
    """
    Per-workspace overrides that deviate from the tier template.
    Only non-inherit keys are stored. Super admin only.
    """
    __tablename__ = "workspace_permission_overrides"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Only keys with "allow" or "deny" are stored here; absent key = inherit
    overrides = Column(JSONB, nullable=False, default=dict)
    permissions_version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_by_user_id = Column(UUID(as_uuid=True), nullable=True)
