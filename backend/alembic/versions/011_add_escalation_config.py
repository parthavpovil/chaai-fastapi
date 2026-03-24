"""add escalation_keywords and escalation_sensitivity to workspaces

Revision ID: 011
Revises: 010
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS escalation_keywords JSONB"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS escalation_sensitivity VARCHAR NOT NULL DEFAULT 'medium'"))


def downgrade() -> None:
    op.drop_column('workspaces', 'escalation_sensitivity')
    op.drop_column('workspaces', 'escalation_keywords')
