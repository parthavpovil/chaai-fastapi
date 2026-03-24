"""add full-text search indexes for conversation search

Revision ID: 010
Revises: 009
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN index for full-text search on message content.
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, so we commit
    # the Alembic transaction first.
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_messages_fts "
        "ON messages USING GIN (to_tsvector('english', content))"
    )

    # Index resolved_at for CSV export date filters
    op.create_index('ix_conversations_resolved_at', 'conversations', ['resolved_at'])


def downgrade() -> None:
    op.drop_index('ix_conversations_resolved_at', table_name='conversations')
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_messages_fts")
