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
    op.add_column('workspaces', sa.Column('metadata', JSONB(), nullable=True))
    op.add_column('workspaces', sa.Column('stripe_customer_id', sa.String(), nullable=True))
    op.add_column('workspaces', sa.Column('stripe_subscription_id', sa.String(), nullable=True))
    op.create_index('ix_workspaces_stripe_customer', 'workspaces', ['stripe_customer_id'])


def downgrade() -> None:
    op.drop_index('ix_workspaces_stripe_customer')
    op.drop_column('workspaces', 'stripe_subscription_id')
    op.drop_column('workspaces', 'stripe_customer_id')
    op.drop_column('workspaces', 'metadata')
