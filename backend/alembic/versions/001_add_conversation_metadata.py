"""add conversation metadata column

Revision ID: 001_add_conversation_metadata
Revises:
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = '001_add_conversation_metadata'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('metadata', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'metadata')
