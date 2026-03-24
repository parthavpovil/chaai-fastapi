"""fix missing columns in contacts and conversations

Revision ID: 014_fix_missing_columns
Revises: 013
Create Date: 2026-03-24

Adds columns that may be missing in DBs originally created via create_all
before these fields were added to the models, and before alembic was adopted.
Uses IF NOT EXISTS so this migration is safe to run on any DB state.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY


revision = '014_fix_missing_columns'
down_revision = '013'
branch_labels = None
depends_on = None


def _add_if_missing(table: str, column: str, col_type: str, default: str = "NULL") -> None:
    """Add a column only if it does not already exist."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table}' AND column_name = '{column}'
            ) THEN
                ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default};
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # ── conversations ────────────────────────────────────────────────────────
    _add_if_missing("conversations", "metadata", "JSONB", "'{}'")
    _add_if_missing("conversations", "resolved_at", "TIMESTAMP WITH TIME ZONE")

    # ── contacts ─────────────────────────────────────────────────────────────
    _add_if_missing("contacts", "email", "VARCHAR")
    _add_if_missing("contacts", "phone", "VARCHAR")
    _add_if_missing("contacts", "source", "VARCHAR")
    _add_if_missing("contacts", "is_blocked", "BOOLEAN", "false")
    _add_if_missing("contacts", "metadata", "JSONB", "'{}'")
    _add_if_missing("contacts", "broadcast_opted_out", "BOOLEAN", "false")
    _add_if_missing("contacts", "opted_out_at", "TIMESTAMP WITH TIME ZONE")
    _add_if_missing("contacts", "custom_fields", "JSONB", "'{}'")

    # tags is an array — handle separately
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'contacts' AND column_name = 'tags'
            ) THEN
                ALTER TABLE contacts ADD COLUMN tags TEXT[] NOT NULL DEFAULT '{}';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # These columns were added by earlier migrations; only drop if this
    # migration added them.  For safety, downgrade is a no-op.
    pass
