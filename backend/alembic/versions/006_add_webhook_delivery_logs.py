"""add webhook delivery logs

Revision ID: 006
Revises: 005
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006'
down_revision = '005_add_platform_extensions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'outbound_webhook_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('webhook_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('response_status_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('is_success', sa.Boolean(), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['webhook_id'], ['outbound_webhooks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_webhook_logs_webhook_delivered', 'outbound_webhook_logs', ['webhook_id', 'delivered_at'])
    op.create_index('ix_webhook_logs_workspace_delivered', 'outbound_webhook_logs', ['workspace_id', 'delivered_at'])


def downgrade() -> None:
    op.drop_index('ix_webhook_logs_workspace_delivered', table_name='outbound_webhook_logs')
    op.drop_index('ix_webhook_logs_webhook_delivered', table_name='outbound_webhook_logs')
    op.drop_table('outbound_webhook_logs')
