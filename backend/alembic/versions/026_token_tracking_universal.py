"""026 token tracking universal

Revision ID: 026_token_tracking_universal
Revises: 025_add_workspace_assistant_persona
Create Date: 2026-05-06

Extends ai_agent_token_log to cover all LLM call types (not just agent calls),
and adds total_cost_usd to usage_counters for monthly cost aggregation.
"""
from alembic import op
import sqlalchemy as sa


revision = "026_token_tracking_universal"
down_revision = "025_add_workspace_assistant_persona"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ai_agent_token_log: add conversation_id + call_source ────────────────
    op.add_column(
        "ai_agent_token_log",
        sa.Column(
            "conversation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "ai_agent_token_log",
        sa.Column("call_source", sa.String(30), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_token_log_conversation "
        "ON ai_agent_token_log (conversation_id) WHERE conversation_id IS NOT NULL"
    )

    # ── usage_counters: add total_cost_usd ───────────────────────────────────
    op.add_column(
        "usage_counters",
        sa.Column(
            "total_cost_usd",
            sa.Numeric(12, 8),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("usage_counters", "total_cost_usd")
    op.execute("DROP INDEX IF EXISTS idx_token_log_conversation")
    op.drop_column("ai_agent_token_log", "call_source")
    op.drop_column("ai_agent_token_log", "conversation_id")
