"""Promote webchat widget_id from encrypted config blob to indexed column

Revision ID: 033_add_channels_widget_id_column
Revises: 032_add_password_reset_pin
Create Date: 2026-05-15

Why: get_webchat_channel_by_widget_id was scanning every active webchat
channel and Fernet-decrypting every field of every config to find one
matching widget_id. With ~25 channels × ~5 encrypted fields × Fernet
overhead this took 10–47 seconds per request and was the root cause of
the nginx 504s on /api/webchat/send. Moving widget_id to its own
top-level indexed column turns the lookup into a sub-millisecond
indexed SELECT.

Steps:
  1. Add nullable widget_id column (metadata-only on PG ≥11 — no rewrite).
  2. Backfill from decrypted config["widget_id"] for every existing
     webchat channel. Migration imports decrypt_credential from the app
     code; ENCRYPTION_KEY must be in the migration container's env (it
     is, via docker-compose.prod.yml).
  3. Create a partial UNIQUE index — non-webchat channels keep widget_id
     NULL and are not constrained.

Rollback is clean: drop index + drop column.
"""
from alembic import op
import sqlalchemy as sa
import logging


revision = "033_add_channels_widget_id_column"
down_revision = "032_add_password_reset_pin"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.033")


def upgrade() -> None:
    # 1. Add nullable column. PG ≥11 makes this metadata-only when there's
    #    no DEFAULT and no NOT NULL — near-instant even on big tables.
    op.add_column(
        "channels",
        sa.Column("widget_id", sa.String(36), nullable=True),
    )

    # 2. Backfill from encrypted config.
    #    Importing app code in a migration is supported by Alembic; the
    #    env.py already loads `app.database`, so settings + encryption
    #    are initialized by the time we get here.
    from app.services.encryption import decrypt_credential

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, config FROM channels "
            "WHERE type = 'webchat' AND config IS NOT NULL"
        )
    ).fetchall()

    backfilled = 0
    fallback_plaintext = 0
    skipped_no_widget_id = 0
    for row in rows:
        encrypted = (row.config or {}).get("widget_id")
        if not encrypted:
            skipped_no_widget_id += 1
            continue
        try:
            plaintext = decrypt_credential(encrypted)
        except Exception as exc:
            # Either a legacy row that was never encrypted, or a row
            # encrypted with an old key. Use the raw value and log so an
            # operator can hand-fix afterwards.
            logger.warning(
                "channel %s: decrypt failed (%s) — using raw config value as widget_id",
                row.id, exc,
            )
            plaintext = encrypted
            fallback_plaintext += 1
        bind.execute(
            sa.text("UPDATE channels SET widget_id = :w WHERE id = :i"),
            {"w": plaintext, "i": row.id},
        )
        backfilled += 1

    logger.info(
        "channels.widget_id backfill: total=%d backfilled=%d fallback_plaintext=%d no_widget_id=%d",
        len(rows), backfilled, fallback_plaintext, skipped_no_widget_id,
    )

    # 3. Partial unique index. Non-webchat channels keep widget_id NULL
    #    and are excluded from the uniqueness check by the WHERE clause.
    #    Not CONCURRENTLY: table is tiny (~25 rows in prod) and the
    #    migration container holds an ACCESS EXCLUSIVE for ms.
    op.execute(
        "CREATE UNIQUE INDEX ix_channels_widget_id "
        "ON channels (widget_id) WHERE widget_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channels_widget_id")
    op.drop_column("channels", "widget_id")
