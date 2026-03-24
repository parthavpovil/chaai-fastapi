"""fix rate_limits table schema to match service expectations

Revision ID: 015_fix_rate_limits_schema
Revises: 014_fix_missing_columns
Create Date: 2026-03-25

Drops the old key/count/reset_at schema and recreates rate_limits with the
columns the RateLimiter service actually uses:
  id, identifier, limit_type, workspace_id, request_timestamps, updated_at
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TIMESTAMP


revision = '015_fix_rate_limits_schema'
down_revision = '014_fix_missing_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old table entirely (rate limit data is transient — safe to discard)
    op.execute("DROP TABLE IF EXISTS rate_limits")

    op.execute("""
        CREATE TABLE rate_limits (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            identifier VARCHAR NOT NULL,
            limit_type VARCHAR NOT NULL,
            workspace_id UUID,
            request_timestamps TIMESTAMP WITH TIME ZONE[] NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_rate_limits_identifier ON rate_limits (identifier)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rate_limits_workspace_id ON rate_limits (workspace_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_limits")
    op.execute("""
        CREATE TABLE rate_limits (
            key VARCHAR PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 1,
            reset_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
