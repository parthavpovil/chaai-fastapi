"""add workspace metadata, ai config, stripe fields

Revision ID: 004_add_workspace_ai_stripe
Revises: 003_add_ai_feedback
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '004_add_workspace_ai_stripe'
down_revision = '003_add_ai_feedback'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS metadata JSONB"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_workspaces_stripe_customer ON workspaces (stripe_customer_id)"))


def downgrade() -> None:
    op.drop_index('ix_workspaces_stripe_customer')
    op.drop_column('workspaces', 'stripe_subscription_id')
    op.drop_column('workspaces', 'stripe_customer_id')
    op.drop_column('workspaces', 'metadata')
