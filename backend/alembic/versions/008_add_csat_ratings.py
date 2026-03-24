"""add csat ratings

Revision ID: 008
Revises: 007
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa_inspect(op.get_bind()).has_table('csat_ratings'):
        op.create_table(
            'csat_ratings',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('contact_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_csat_rating_range'),
            sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('conversation_id', name='uq_csat_per_conversation'),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_csat_workspace_submitted ON csat_ratings (workspace_id, submitted_at)"))

    # Add resolved_at to conversations (used by CSV export and CSAT analytics)
    op.execute(sa.text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ"))


def downgrade() -> None:
    op.drop_column('conversations', 'resolved_at')
    op.drop_index('ix_csat_workspace_submitted', table_name='csat_ratings')
    op.drop_table('csat_ratings')
