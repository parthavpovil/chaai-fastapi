"""add workspace-specific escalation acknowledgment messages

Revision ID: 021_add_escalation_messages
Revises: 020_add_email_logs
Create Date: 2026-03-26

Changes:
- Add escalation_message_with_agents column to workspaces (nullable text)
- Add escalation_message_without_agents column to workspaces (nullable text)
  When null, hardcoded defaults are used. When set, shown to customers on escalation.
"""

from alembic import op
import sqlalchemy as sa

revision = "021_add_escalation_messages"
down_revision = "020_add_email_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("escalation_message_with_agents", sa.Text(), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("escalation_message_without_agents", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "escalation_message_without_agents")
    op.drop_column("workspaces", "escalation_message_with_agents")
