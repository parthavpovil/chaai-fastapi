"""add email_logs table

Revision ID: 020_add_email_logs
Revises: 019_escalation_email_enabled
Create Date: 2026-03-26

Changes:
- Create email_logs table to persist Resend webhook events
  (sent, delivered, bounced, complained, opened, clicked, delayed)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "020_add_email_logs"
down_revision = "019_escalation_email_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("email_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("recipient", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_email_logs_email_id", "email_logs", ["email_id"])
    op.create_index("ix_email_logs_workspace_id", "email_logs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_email_logs_workspace_id", table_name="email_logs")
    op.drop_index("ix_email_logs_email_id", table_name="email_logs")
    op.drop_table("email_logs")
