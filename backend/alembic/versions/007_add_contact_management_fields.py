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
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email VARCHAR"))
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS phone VARCHAR"))
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}'"))
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS custom_fields JSONB NOT NULL DEFAULT '{}'"))
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS source VARCHAR"))
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT false"))
    op.execute(sa.text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'"))

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_contacts_tags ON contacts USING GIN (tags)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_contacts_workspace_blocked ON contacts (workspace_id, is_blocked)"))


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
