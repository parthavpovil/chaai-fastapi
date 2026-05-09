"""
Permission resolution service.

Computes the effective permission map for a workspace+role combination by:
  1. Loading the tier's template flags from DB (fallback to DEFAULT_TIER_FLAGS).
  2. Applying per-workspace overrides (allow / deny).
  3. Masking with the agent role ceiling when role == "agent".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import TierPermissionTemplate, WorkspacePermissionOverride
from app.models.workspace import Workspace

# ---------------------------------------------------------------------------
# Registry — canonical set of all permission keys
# ---------------------------------------------------------------------------
PERMISSION_REGISTRY: list[str] = [
    "dashboard.home",
    "inbox.core",
    "inbox.claim",
    "inbox.my_active",
    "inbox.export",
    "contacts.directory",
    "contacts.moderation",
    "channels.manage",
    "team.manage",
    "knowledge_base.documents",
    "ai.workspace_settings",
    "ai.agents_studio",
    "automation.flows",
    "automation.templates",
    "automation.broadcasts",
    "productivity.canned_responses",
    "productivity.assignment_rules",
    "productivity.business_hours",
    "integrations.outbound_webhooks",
    "integrations.api_keys",
    "billing.manage",
    "workspace.settings",
    "analytics.csat",
    "analytics.workspace_metrics",
    "analytics.system",
    "agent_self.presence",
    "realtime.staff_ws",
]

# Keys agents may ever receive as True (regardless of tier/overrides)
AGENT_CEILING: frozenset[str] = frozenset(
    [
        "dashboard.home",
        "inbox.core",
        "inbox.claim",
        "inbox.my_active",
        "inbox.export",
        "contacts.directory",
        "productivity.canned_responses",
        "agent_self.presence",
        "realtime.staff_ws",
    ]
)

# Hardcoded fallback defaults — used when DB tier template row is missing
DEFAULT_TIER_FLAGS: dict[str, dict[str, bool]] = {
    "free": {
        "dashboard.home": True,
        "inbox.core": True,
        "inbox.claim": False,
        "inbox.my_active": False,
        "inbox.export": False,
        "contacts.directory": True,
        "contacts.moderation": True,
        "channels.manage": True,
        "team.manage": False,
        "knowledge_base.documents": False,
        "ai.workspace_settings": False,
        "ai.agents_studio": False,
        "automation.flows": True,
        "automation.templates": True,
        "automation.broadcasts": True,
        "productivity.canned_responses": True,
        "productivity.assignment_rules": False,
        "productivity.business_hours": True,
        "integrations.outbound_webhooks": False,
        "integrations.api_keys": False,
        "billing.manage": True,
        "workspace.settings": True,
        "analytics.csat": False,
        "analytics.workspace_metrics": True,
        "analytics.system": True,
        "agent_self.presence": False,
        "realtime.staff_ws": True,
    },
    "starter": {
        "dashboard.home": True,
        "inbox.core": True,
        "inbox.claim": False,
        "inbox.my_active": False,
        "inbox.export": False,
        "contacts.directory": True,
        "contacts.moderation": True,
        "channels.manage": True,
        "team.manage": False,
        "knowledge_base.documents": True,
        "ai.workspace_settings": False,
        "ai.agents_studio": True,
        "automation.flows": True,
        "automation.templates": True,
        "automation.broadcasts": True,
        "productivity.canned_responses": True,
        "productivity.assignment_rules": False,
        "productivity.business_hours": True,
        "integrations.outbound_webhooks": False,
        "integrations.api_keys": False,
        "billing.manage": True,
        "workspace.settings": True,
        "analytics.csat": False,
        "analytics.workspace_metrics": True,
        "analytics.system": True,
        "agent_self.presence": False,
        "realtime.staff_ws": True,
    },
    "growth": {
        "dashboard.home": True,
        "inbox.core": True,
        "inbox.claim": False,
        "inbox.my_active": False,
        "inbox.export": True,
        "contacts.directory": True,
        "contacts.moderation": True,
        "channels.manage": True,
        "team.manage": False,
        "knowledge_base.documents": True,
        "ai.workspace_settings": True,
        "ai.agents_studio": True,
        "automation.flows": True,
        "automation.templates": True,
        "automation.broadcasts": True,
        "productivity.canned_responses": True,
        "productivity.assignment_rules": False,
        "productivity.business_hours": True,
        "integrations.outbound_webhooks": True,
        "integrations.api_keys": True,
        "billing.manage": True,
        "workspace.settings": True,
        "analytics.csat": True,
        "analytics.workspace_metrics": True,
        "analytics.system": True,
        "agent_self.presence": False,
        "realtime.staff_ws": True,
    },
    "pro": {
        "dashboard.home": True,
        "inbox.core": True,
        "inbox.claim": True,
        "inbox.my_active": True,
        "inbox.export": True,
        "contacts.directory": True,
        "contacts.moderation": True,
        "channels.manage": True,
        "team.manage": True,
        "knowledge_base.documents": True,
        "ai.workspace_settings": True,
        "ai.agents_studio": True,
        "automation.flows": True,
        "automation.templates": True,
        "automation.broadcasts": True,
        "productivity.canned_responses": True,
        "productivity.assignment_rules": True,
        "productivity.business_hours": True,
        "integrations.outbound_webhooks": True,
        "integrations.api_keys": True,
        "billing.manage": True,
        "workspace.settings": True,
        "analytics.csat": True,
        "analytics.workspace_metrics": True,
        "analytics.system": True,
        "agent_self.presence": True,
        "realtime.staff_ws": True,
    },
}


async def _load_tier_flags(tier_id: str, db: AsyncSession) -> dict[str, bool]:
    """Load tier template from DB; fall back to hardcoded defaults."""
    result = await db.execute(
        select(TierPermissionTemplate).where(TierPermissionTemplate.tier_id == tier_id)
    )
    template = result.scalar_one_or_none()
    if template and template.flags:
        return dict(template.flags)
    return DEFAULT_TIER_FLAGS.get(tier_id, DEFAULT_TIER_FLAGS["free"]).copy()


async def _load_overrides(workspace_id: Any, db: AsyncSession) -> dict[str, str]:
    """Load workspace overrides. Returns empty dict if none exist."""
    result = await db.execute(
        select(WorkspacePermissionOverride).where(
            WorkspacePermissionOverride.workspace_id == workspace_id
        )
    )
    row = result.scalar_one_or_none()
    if row and row.overrides:
        return dict(row.overrides)
    return {}


async def get_effective_permissions(
    workspace: Workspace,
    role: str,
    db: AsyncSession,
) -> dict[str, bool]:
    """
    Return the effective flat permission map for a workspace+role.

    Result is cached in Redis for 60 s (permissions change at most once per
    hour on tier upgrades or explicit overrides).  Cache is invalidated by
    workspace_cache.invalidate_workspace_cache() when tier or overrides change.

    Returns:
        Flat dict: {"dashboard.home": True, "inbox.claim": False, ...}
    """
    from app.services.workspace_cache import get_cached_permissions, set_cached_permissions

    workspace_id_str = str(workspace.id)
    cached = await get_cached_permissions(workspace_id_str, role)
    if cached is not None:
        return cached

    tier_id = workspace.tier or "free"
    tier_flags = await _load_tier_flags(tier_id, db)
    overrides = await _load_overrides(workspace.id, db)

    effective: dict[str, bool] = {}
    for key in PERMISSION_REGISTRY:
        override = overrides.get(key)
        if override == "allow":
            base = True
        elif override == "deny":
            base = False
        else:
            base = bool(tier_flags.get(key, False))

        if role == "agent":
            effective[key] = base and (key in AGENT_CEILING)
        else:
            effective[key] = base

    await set_cached_permissions(workspace_id_str, role, effective)
    return effective


def build_nested_response(flat: dict[str, bool]) -> dict[str, dict[str, bool]]:
    """Convert flat "area.feature" dict to nested {"area": {"feature": bool}}."""
    nested: dict[str, dict[str, bool]] = {}
    for key, value in flat.items():
        area, _, feature = key.partition(".")
        nested.setdefault(area, {})[feature] = value
    return nested


async def get_override_row(
    workspace_id: Any, db: AsyncSession
) -> WorkspacePermissionOverride | None:
    result = await db.execute(
        select(WorkspacePermissionOverride).where(
            WorkspacePermissionOverride.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


async def upsert_overrides(
    workspace_id: Any,
    new_overrides: dict[str, str],
    actor_user_id: Any,
    db: AsyncSession,
) -> WorkspacePermissionOverride:
    """
    Merge new_overrides into the existing workspace override row.
    Values of "inherit" remove the key; "allow"/"deny" set it.
    Increments permissions_version.
    """
    row = await get_override_row(workspace_id, db)
    now = datetime.now(timezone.utc)

    if row is None:
        merged = {}
        version = 1
    else:
        merged = dict(row.overrides or {})
        version = (row.permissions_version or 1) + 1

    for key, value in new_overrides.items():
        if value == "inherit":
            merged.pop(key, None)
        else:
            merged[key] = value

    if row is None:
        row = WorkspacePermissionOverride(
            workspace_id=workspace_id,
            overrides=merged,
            permissions_version=version,
            updated_at=now,
            updated_by_user_id=actor_user_id,
        )
        db.add(row)
    else:
        row.overrides = merged
        row.permissions_version = version
        row.updated_at = now
        row.updated_by_user_id = actor_user_id

    await db.commit()
    await db.refresh(row)

    from app.services.workspace_cache import invalidate_workspace_cache
    await invalidate_workspace_cache(str(workspace_id))

    return row
