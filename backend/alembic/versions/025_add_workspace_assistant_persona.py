"""add workspace assistant persona fields

Revision ID: 025_add_workspace_assistant_persona
Revises: 024_add_permission_tables
Create Date: 2026-05-03

Changes:
- Add assistant_name column to workspaces (VARCHAR(60), nullable). The bot's
  display name (e.g. "Mocha", "Sage"). Null falls back to the default opener.
- Add assistant_persona column to workspaces (VARCHAR(300), nullable). A short
  role descriptor (e.g. "a friendly cafe assistant for Brew & Co"). Null is
  omitted from the system prompt.
"""

from alembic import op
import sqlalchemy as sa

revision = "025_add_workspace_assistant_persona"
down_revision = "024_add_permission_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("assistant_name", sa.String(length=60), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("assistant_persona", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "assistant_persona")
    op.drop_column("workspaces", "assistant_name")
