"""add conversation metadata column

Revision ID: 001_add_conversation_metadata
Revises: 0001
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = '001_add_conversation_metadata'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS metadata JSONB"))


def downgrade() -> None:
    op.drop_column('conversations', 'metadata')
