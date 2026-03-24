"""add contact management fields

Revision ID: 007
Revises: 006
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('email', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('phone', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'))
    op.add_column('contacts', sa.Column('custom_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'))
    op.add_column('contacts', sa.Column('source', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('contacts', sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'))

    op.create_index('ix_contacts_tags', 'contacts', ['tags'], postgresql_using='gin')
    op.create_index('ix_contacts_workspace_blocked', 'contacts', ['workspace_id', 'is_blocked'])


def downgrade() -> None:
    op.drop_index('ix_contacts_workspace_blocked', table_name='contacts')
    op.drop_index('ix_contacts_tags', table_name='contacts')
    op.drop_column('contacts', 'metadata')
    op.drop_column('contacts', 'is_blocked')
    op.drop_column('contacts', 'source')
    op.drop_column('contacts', 'custom_fields')
    op.drop_column('contacts', 'tags')
    op.drop_column('contacts', 'phone')
    op.drop_column('contacts', 'email')
