"""add missing columns to messages table

Revision ID: 016_add_missing_message_columns
Revises: 015_fix_rate_limits_schema
Create Date: 2026-03-25

Adds columns present in the Message model that may be missing on DBs that
were created before these fields were added. Uses IF NOT EXISTS so safe to
run on any DB state.
"""
from alembic import op


revision = '016_add_missing_message_columns'
down_revision = '015_fix_rate_limits_schema'
branch_labels = None
depends_on = None


def _add_if_missing(table: str, column: str, col_type: str, default: str = "NULL") -> None:
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
    # message_type / media / location / delivery columns
    _add_if_missing("messages", "message_type",      "VARCHAR",                     "'text'")
    _add_if_missing("messages", "media_url",          "VARCHAR")
    _add_if_missing("messages", "media_mime_type",    "VARCHAR")
    _add_if_missing("messages", "media_filename",     "VARCHAR")
    _add_if_missing("messages", "media_size",         "INTEGER")
    _add_if_missing("messages", "location_lat",       "FLOAT")
    _add_if_missing("messages", "location_lng",       "FLOAT")
    _add_if_missing("messages", "location_name",      "VARCHAR")
    _add_if_missing("messages", "whatsapp_message_id","VARCHAR")
    _add_if_missing("messages", "delivery_status",    "VARCHAR")
    _add_if_missing("messages", "sent_at",            "TIMESTAMP WITH TIME ZONE")
    _add_if_missing("messages", "delivered_at",       "TIMESTAMP WITH TIME ZONE")
    _add_if_missing("messages", "read_at",            "TIMESTAMP WITH TIME ZONE")
    _add_if_missing("messages", "failed_reason",      "VARCHAR")


def downgrade() -> None:
    pass
