"""add escalation_keywords and escalation_sensitivity to workspaces

Revision ID: 011
Revises: 010
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('workspaces', sa.Column('escalation_keywords', JSONB, nullable=True))
    op.add_column('workspaces', sa.Column(
        'escalation_sensitivity',
        sa.String,
        nullable=False,
        server_default='medium'
    ))


def downgrade() -> None:
    op.drop_column('workspaces', 'escalation_sensitivity')
    op.drop_column('workspaces', 'escalation_keywords')
