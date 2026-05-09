"""Add deleted_at to workspaces for soft-delete support

Revision ID: 029_add_workspace_soft_delete
Revises: 028_add_messages_external_id_unique
Create Date: 2026-05-07

Replaces the hard-delete path (db.delete(workspace) → cascade destroys 17 tables)
with a soft-delete: setting deleted_at timestamps the workspace as deleted without
touching any child data. A future hard-delete reaper can purge rows older than 30 days.

Adding a nullable column is a safe online operation — no table rewrite, no lock.
"""
from alembic import op
import sqlalchemy as sa

revision = "029_add_workspace_soft_delete"
down_revision = "028_add_messages_external_id_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index — only covers soft-deleted rows; used by a future hard-delete reaper.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workspaces_deleted_at "
        "ON workspaces (deleted_at) WHERE deleted_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workspaces_deleted_at")
    op.drop_column("workspaces", "deleted_at")
