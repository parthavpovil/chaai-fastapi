"""Add tier_permission_templates and workspace_permission_overrides tables

Revision ID: 024_add_permission_tables
Revises: 023_hnsw_fts_chunks
Create Date: 2026-04-03

Changes:
- Create tier_permission_templates table: one row per billing tier with a JSONB
  flags map covering all ~27 permission keys.
- Create workspace_permission_overrides table: per-workspace overrides (allow/deny)
  that deviate from the tier template. Cascades on workspace deletion.
- Seed default tier templates derived from existing TIER_LIMITS configuration.
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "024_add_permission_tables"
down_revision = "023_hnsw_fts_chunks"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Default flags per tier — mirrors TIER_LIMITS in app/config.py
# ---------------------------------------------------------------------------
_DEFAULT_TIER_FLAGS = {
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


def upgrade() -> None:
    op.create_table(
        "tier_permission_templates",
        sa.Column("tier_id", sa.String(), primary_key=True),
        sa.Column("flags", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("updated_by_user_id", UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "workspace_permission_overrides",
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("overrides", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "permissions_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("updated_by_user_id", UUID(as_uuid=True), nullable=True),
    )

    # Seed default tier templates
    now = datetime.now(timezone.utc)
    tpl_table = sa.table(
        "tier_permission_templates",
        sa.column("tier_id", sa.String),
        sa.column("flags", JSONB),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        tpl_table,
        [
            {"tier_id": tier_id, "flags": flags, "updated_at": now}
            for tier_id, flags in _DEFAULT_TIER_FLAGS.items()
        ],
    )


def downgrade() -> None:
    op.drop_table("workspace_permission_overrides")
    op.drop_table("tier_permission_templates")
