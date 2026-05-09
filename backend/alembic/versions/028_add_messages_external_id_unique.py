"""Add partial unique index on messages(conversation_id, external_message_id)

Revision ID: 028_add_messages_external_id_unique
Revises: 027_add_conversation_workspace_updated_index
Create Date: 2026-05-07

Prevents duplicate inbound messages when carriers retry webhook delivery.
The model comment promised this index since the initial schema; it was never created.

Scoped to (conversation_id, external_message_id) — NOT just external_message_id alone.
Telegram message IDs are sequential integers per chat (1, 2, 3...) and would
collide across workspaces under a global unique index.

Partial (WHERE external_message_id IS NOT NULL) so webchat and outbound
assistant messages, which have no external ID, are unaffected.

BEFORE RUNNING: verify no existing duplicates with:
  SELECT conversation_id, external_message_id, COUNT(*)
  FROM messages
  WHERE external_message_id IS NOT NULL
  GROUP BY conversation_id, external_message_id
  HAVING COUNT(*) > 1;
If rows are returned, deduplicate them first (keep the oldest id, delete the rest).
"""
from alembic import op

revision = "028_add_messages_external_id_unique"
down_revision = "027_add_conversation_workspace_updated_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY requires stepping outside Alembic's implicit transaction.
    op.execute("COMMIT")
    op.execute(
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_messages_external_id_unique "
        "ON messages (conversation_id, external_message_id) "
        "WHERE external_message_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_messages_external_id_unique"
    )
