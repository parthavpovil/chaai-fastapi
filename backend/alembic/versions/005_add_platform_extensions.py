"""add outbound_webhooks and api_keys tables

Revision ID: 005_add_platform_extensions
Revises: 004_add_workspace_ai_stripe
Create Date: 2026-03-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '005_add_platform_extensions'
down_revision = '004_add_workspace_ai_stripe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa_inspect(op.get_bind())

    # Outbound webhooks
    if not insp.has_table('outbound_webhooks'):
        op.create_table(
            'outbound_webhooks',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('url', sa.String(), nullable=False),
            sa.Column('events', JSONB(), nullable=False),
            sa.Column('secret', sa.String(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_outbound_webhooks_workspace ON outbound_webhooks (workspace_id)"))

    # API keys
    if not insp.has_table('api_keys'):
        op.create_table(
            'api_keys',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('key_hash', sa.String(), nullable=False, unique=True),
            sa.Column('prefix', sa.String(), nullable=False),
            sa.Column('scopes', JSONB(), nullable=True),
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_api_keys_workspace ON api_keys (workspace_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)"))


def downgrade() -> None:
    op.drop_table('api_keys')
    op.drop_table('outbound_webhooks')
