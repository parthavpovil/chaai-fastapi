"""Add composite index on conversations(workspace_id, updated_at DESC)

Revision ID: 027_add_conversation_workspace_updated_index
Revises: 026_token_tracking_universal
Create Date: 2026-05-07

Every conversation list call filters by workspace_id and orders by updated_at DESC.
Without this index Postgres does a full-table scan + in-memory sort on every request.
At scale (100k+ rows) this becomes the dominant slow query on the dashboard.

CREATE INDEX CONCURRENTLY is used to avoid a table-level lock on the live database.
Note: CONCURRENTLY cannot run inside a transaction, so we commit Alembic's implicit
transaction first (same pattern as migration 010).
"""
from alembic import op

revision = "027_add_conversation_workspace_updated_index"
down_revision = "026_token_tracking_universal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step outside Alembic's implicit transaction — required for CONCURRENTLY.
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_conversations_workspace_updated "
        "ON conversations (workspace_id, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_conversations_workspace_updated"
    )
