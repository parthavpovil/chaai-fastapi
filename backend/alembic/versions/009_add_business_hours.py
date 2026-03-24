"""add business hours

Revision ID: 009
Revises: 008
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'business_hours',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('day_of_week', sa.Integer(), nullable=False),
        sa.Column('open_time', sa.Time(), nullable=True),
        sa.Column('close_time', sa.Time(), nullable=True),
        sa.Column('is_closed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('timezone', sa.String(), nullable=False, server_default='UTC'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('day_of_week BETWEEN 0 AND 6', name='ck_business_hours_day_range'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'day_of_week', name='uq_business_hours_day'),
    )

    op.add_column('workspaces', sa.Column('outside_hours_message', sa.Text(), nullable=True))
    op.add_column('workspaces', sa.Column('outside_hours_behavior', sa.String(), nullable=True, server_default='inform_and_continue'))


def downgrade() -> None:
    op.drop_column('workspaces', 'outside_hours_behavior')
    op.drop_column('workspaces', 'outside_hours_message')
    op.drop_table('business_hours')
