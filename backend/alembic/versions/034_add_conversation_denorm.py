"""Add denormalized last_message_at + message_count to conversations

Revision ID: 034_add_conversation_denorm
Revises: 033_add_channels_widget_id_column
Create Date: 2026-05-16

Why: /conversations list endpoint issued 1 + 2*limit SQL queries per request
(at default limit=50 that's 101 queries) — one outer list query, plus a
last-message SELECT and a COUNT(*) per row. Dashboard polling at 10s
intervals × 100 users = ~1010 q/s for one endpoint.

Two denormalized columns on conversations eliminate the N count queries
entirely (message_count), and let the read path replace the N last-message
queries with a single batched DISTINCT ON (conversation_id) (last_message_at
is used by the read path's ORDER BY and as a sanity check on the batched
fetch).

Steps:
  1. Add last_message_at (timestamptz, nullable).
  2. Add message_count (integer, NOT NULL, server_default '0').
  3. Backfill both from the messages table in a single UPDATE … FROM (GROUP BY).
  4. Add a compound index on (workspace_id, last_message_at DESC) for the
     dashboard's order-by-recency list query.

Lock behavior: the backfill UPDATE acquires row locks on every conversation
that has at least one message. ACCESS EXCLUSIVE is NOT held — the AddColumn
operations on PG ≥11 with nullable + no default are metadata-only (near-
instant), and the index creation here is NOT CONCURRENTLY (matches codebase
pattern; the migration container runs during deploy maintenance windows).
Estimated wall time: O(rows in messages) sequential scan + GROUP BY + N
indexed row updates on conversations — single-digit minutes on a 10M-message
table. If the messages table is materially larger than expected, abort and
re-run with a deferred-backfill strategy (separate script + code fallback).

Rollback is clean: drop index + drop both columns.
"""
from alembic import op
import sqlalchemy as sa
import logging


revision = "034_add_conversation_denorm"
down_revision = "033_add_channels_widget_id_column"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.034")


def upgrade() -> None:
    # 1 + 2. Add columns. nullable=True for last_message_at; server_default='0'
    # NOT NULL for message_count so reads never see NULL. On PG ≥11 these are
    # metadata-only (no table rewrite) because last_message_at has no default
    # and message_count's default is a constant.
    op.add_column(
        "conversations",
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # 3. Backfill from messages. Single statement; PG groups the messages
    # table once and joins back to conversations by conversation_id.
    op.execute(
        """
        UPDATE conversations c
        SET last_message_at = sub.last_at,
            message_count   = sub.cnt
        FROM (
            SELECT conversation_id,
                   MAX(created_at) AS last_at,
                   COUNT(*)        AS cnt
            FROM messages
            GROUP BY conversation_id
        ) sub
        WHERE c.id = sub.conversation_id
        """
    )

    # 4. Index for the dashboard list query: WHERE workspace_id = $1
    # ORDER BY last_message_at DESC LIMIT N. last_message_at NULL rows
    # (conversations with no messages) sort last by default — fine for
    # a "recent activity" list.
    op.create_index(
        "ix_conversations_workspace_lastmsg",
        "conversations",
        ["workspace_id", sa.text("last_message_at DESC")],
    )

    logger.info("conversations.last_message_at + message_count backfilled")


def downgrade() -> None:
    op.drop_index(
        "ix_conversations_workspace_lastmsg",
        table_name="conversations",
    )
    op.drop_column("conversations", "message_count")
    op.drop_column("conversations", "last_message_at")
