"""add escalation_email_enabled to workspaces

Revision ID: 019_escalation_email_enabled
Revises: 018_chunks_openai_1536
Create Date: 2026-03-25

Changes:
- Add escalation_email_enabled boolean column to workspaces (default True)
"""

from alembic import op
import sqlalchemy as sa

revision = "019_escalation_email_enabled"
down_revision = "018_chunks_openai_1536"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("escalation_email_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "escalation_email_enabled")
