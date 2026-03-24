"""add ai_agent tables

Revision ID: 013
Revises: 012
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa_inspect(op.get_bind())

    # ai_agents — uses ai_agents to avoid collision with existing 'agents' table
    if not insp.has_table('ai_agents'):
        op.create_table(
            'ai_agents',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('system_prompt', sa.Text, nullable=False),
            sa.Column('persona_name', sa.String(50), nullable=True),
            sa.Column('persona_tone', sa.String(50), server_default='friendly'),
            sa.Column('first_message', sa.Text, nullable=True),
            sa.Column('escalation_trigger', sa.String(50), server_default='low_confidence'),
            sa.Column('escalation_message', sa.Text, server_default='Let me connect you with a team member.'),
            sa.Column('confidence_threshold', sa.Float, server_default='0.7'),
            sa.Column('max_turns', sa.Integer, server_default='10'),
            sa.Column('token_budget', sa.Integer, server_default='8000'),
            sa.Column('is_active', sa.Boolean, server_default='true'),
            sa.Column('is_draft', sa.Boolean, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        )

    if not insp.has_table('ai_agent_tools'):
        op.create_table(
            'ai_agent_tools',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('ai_agents.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('display_name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text, nullable=False),
            sa.Column('method', sa.String(10), server_default='GET'),
            sa.Column('endpoint_url', sa.Text, nullable=False),
            sa.Column('headers', JSONB, server_default='{}'),
            sa.Column('body_template', JSONB, nullable=True),
            sa.Column('parameters', JSONB, nullable=False, server_default='[]'),
            sa.Column('response_path', sa.Text, nullable=True),
            sa.Column('requires_confirmation', sa.Boolean, server_default='false'),
            sa.Column('is_read_only', sa.Boolean, server_default='true'),
            sa.Column('is_active', sa.Boolean, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        )

    if not insp.has_table('ai_agent_guardrails'):
        op.create_table(
            'ai_agent_guardrails',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('ai_agents.id', ondelete='CASCADE'), nullable=False),
            sa.Column('rule_type', sa.String(30), nullable=False),
            sa.Column('description', sa.Text, nullable=False),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        )

    if not insp.has_table('ai_agent_channel_assignments'):
        op.create_table(
            'ai_agent_channel_assignments',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('ai_agents.id', ondelete='CASCADE'), nullable=False),
            sa.Column('channel_id', UUID(as_uuid=True), sa.ForeignKey('channels.id', ondelete='CASCADE'), nullable=False),
            sa.Column('priority', sa.Integer, server_default='0'),
            sa.Column('is_active', sa.Boolean, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.UniqueConstraint('channel_id', 'agent_id', name='uq_channel_agent'),
        )

    if not insp.has_table('ai_agent_conversations'):
        op.create_table(
            'ai_agent_conversations',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('ai_agents.id'), nullable=False),
            sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id'), nullable=False),
            sa.Column('status', sa.String(20), server_default='active'),
            sa.Column('turn_count', sa.Integer, server_default='0'),
            sa.Column('escalation_reason', sa.Text, nullable=True),
            sa.Column('total_input_tokens', sa.Integer, server_default='0'),
            sa.Column('total_output_tokens', sa.Integer, server_default='0'),
            sa.Column('started_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('ended_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        )

    if not insp.has_table('ai_agent_token_log'):
        op.create_table(
            'ai_agent_token_log',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id'), nullable=False),
            sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('ai_agents.id'), nullable=True),
            sa.Column('agent_conversation_id', UUID(as_uuid=True), sa.ForeignKey('ai_agent_conversations.id'), nullable=True),
            sa.Column('model', sa.String(50), nullable=False),
            sa.Column('call_type', sa.String(30), nullable=False),
            sa.Column('input_tokens', sa.Integer, nullable=False),
            sa.Column('output_tokens', sa.Integer, nullable=False),
            sa.Column('total_cost_usd', sa.Numeric(10, 8), nullable=False),
            sa.Column('tool_name', sa.String(100), nullable=True),
            sa.Column('tool_latency_ms', sa.Integer, nullable=True),
            sa.Column('tool_success', sa.Boolean, nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        )

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_ai_token_log_workspace ON ai_agent_token_log (workspace_id, created_at)"))


def downgrade() -> None:
    op.drop_index('idx_ai_token_log_workspace', table_name='ai_agent_token_log')
    op.drop_table('ai_agent_token_log')
    op.drop_table('ai_agent_conversations')
    op.drop_table('ai_agent_channel_assignments')
    op.drop_table('ai_agent_guardrails')
    op.drop_table('ai_agent_tools')
    op.drop_table('ai_agents')
