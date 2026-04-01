"""add workspace routing mode settings

Revision ID: 022_add_routing_settings
Revises: 021_add_escalation_messages
Create Date: 2026-04-01

Changes:
- Add ai_enabled boolean column to workspaces (default True, NOT NULL)
  When False, all LLM processing is skipped entirely.
- Add auto_escalation_enabled boolean column to workspaces (default True, NOT NULL)
  When False, the escalation classifier never runs automatically; human agents
  can still receive conversations via manual escalation from the dashboard.

Combined with the existing agents_enabled column, these two new columns give
workspace owners full control over which of the three response capabilities
(RAG AI, AI Agent, Human Agent) are active in any combination.
"""

from alembic import op
import sqlalchemy as sa

revision = "022_add_routing_settings"
down_revision = "021_add_escalation_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "ai_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "auto_escalation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "auto_escalation_enabled")
    op.drop_column("workspaces", "ai_enabled")
