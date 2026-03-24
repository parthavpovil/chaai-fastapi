"""add ai_feedback table

Revision ID: 003_add_ai_feedback
Revises: 002_add_agent_workspace_models
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '003_add_ai_feedback'
down_revision = '002_add_agent_workspace_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_feedback',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rating', sa.String(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('message_id', name='uq_ai_feedback_message'),
    )
    op.create_index('ix_ai_feedback_workspace', 'ai_feedback', ['workspace_id'])


def downgrade() -> None:
    op.drop_table('ai_feedback')
