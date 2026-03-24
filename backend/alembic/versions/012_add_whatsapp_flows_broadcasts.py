"""add flows, whatsapp_templates, broadcasts tables

Revision ID: 012
Revises: 011
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa_inspect(op.get_bind())

    # flows
    if not insp.has_table('flows'):
        op.create_table(
            'flows',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('trigger_keywords', ARRAY(sa.String), nullable=True),
            sa.Column('trigger_type', sa.String(20), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('steps', JSONB, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_flows_workspace_id ON flows (workspace_id)"))

    # conversation_flow_states
    if not insp.has_table('conversation_flow_states'):
        op.create_table(
            'conversation_flow_states',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False, unique=True),
            sa.Column('flow_id', UUID(as_uuid=True), sa.ForeignKey('flows.id'), nullable=False),
            sa.Column('current_step_id', sa.String(50), nullable=False),
            sa.Column('collected_data', JSONB),
            sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('abandoned_at', sa.DateTime(timezone=True), nullable=True),
        )

    # whatsapp_templates
    if not insp.has_table('whatsapp_templates'):
        op.create_table(
            'whatsapp_templates',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('category', sa.String(20), nullable=False),
            sa.Column('language', sa.String(10), nullable=False),
            sa.Column('status', sa.String(20), default='draft'),
            sa.Column('rejection_reason', sa.Text, nullable=True),
            sa.Column('header_type', sa.String(20), nullable=True),
            sa.Column('header_content', sa.Text, nullable=True),
            sa.Column('body', sa.Text, nullable=False),
            sa.Column('footer', sa.Text, nullable=True),
            sa.Column('buttons', JSONB, nullable=True),
            sa.Column('meta_template_id', sa.String(100), nullable=True),
            sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_whatsapp_templates_workspace_id ON whatsapp_templates (workspace_id)"))

    # broadcasts
    if not insp.has_table('broadcasts'):
        op.create_table(
            'broadcasts',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('template_id', UUID(as_uuid=True), sa.ForeignKey('whatsapp_templates.id'), nullable=False),
            sa.Column('variable_mapping', JSONB, nullable=True),
            sa.Column('audience_type', sa.String(20), nullable=False),
            sa.Column('audience_filter', JSONB, nullable=True),
            sa.Column('recipient_count', sa.Integer, nullable=True),
            sa.Column('status', sa.String(20), default='draft'),
            sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_broadcasts_workspace_id ON broadcasts (workspace_id)"))

    # broadcast_recipients
    if not insp.has_table('broadcast_recipients'):
        op.create_table(
            'broadcast_recipients',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('broadcast_id', UUID(as_uuid=True), sa.ForeignKey('broadcasts.id'), nullable=False),
            sa.Column('contact_id', UUID(as_uuid=True), sa.ForeignKey('contacts.id'), nullable=False),
            sa.Column('phone', sa.String(20), nullable=False),
            sa.Column('variable_values', JSONB, nullable=True),
            sa.Column('status', sa.String(20), default='pending'),
            sa.Column('whatsapp_message_id', sa.String(100), nullable=True),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('failed_reason', sa.Text, nullable=True),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_broadcast_recipients_broadcast_id ON broadcast_recipients (broadcast_id)"))


def downgrade() -> None:
    op.drop_table('broadcast_recipients')
    op.drop_table('broadcasts')
    op.drop_table('whatsapp_templates')
    op.drop_table('conversation_flow_states')
    op.drop_table('flows')
