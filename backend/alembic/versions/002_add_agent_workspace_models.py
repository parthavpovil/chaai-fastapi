"""add agent status, internal notes, canned responses, assignment rules

Revision ID: 002_add_agent_workspace_models
Revises: 001_add_conversation_metadata
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '002_add_agent_workspace_models'
down_revision = '001_add_conversation_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agent status fields
    op.execute(sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'offline'"))
    op.execute(sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ"))

    insp = sa_inspect(op.get_bind())

    # Internal notes
    if not insp.has_table('internal_notes'):
        op.create_table(
            'internal_notes',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_internal_notes_conversation ON internal_notes (conversation_id)"))

    # Canned responses
    if not insp.has_table('canned_responses'):
        op.create_table(
            'canned_responses',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('shortcut', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint('workspace_id', 'shortcut', name='uq_canned_response_shortcut'),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_canned_responses_workspace ON canned_responses (workspace_id)"))

    # Assignment rules
    if not insp.has_table('assignment_rules'):
        op.create_table(
            'assignment_rules',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
            sa.Column('conditions', JSONB(), nullable=True),
            sa.Column('action', sa.String(), nullable=False, server_default='round_robin'),
            sa.Column('target_agent_id', UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_assignment_rules_workspace_priority ON assignment_rules (workspace_id, priority)"))


def downgrade() -> None:
    op.drop_table('assignment_rules')
    op.drop_table('canned_responses')
    op.drop_table('internal_notes')
    op.drop_column('agents', 'last_heartbeat_at')
    op.drop_column('agents', 'status')
