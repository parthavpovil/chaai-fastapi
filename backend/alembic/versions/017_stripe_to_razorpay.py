"""migrate billing columns from stripe to razorpay

Revision ID: 017_stripe_to_razorpay
Revises: 016_add_missing_message_columns
Create Date: 2026-03-25

Renames stripe_customer_id -> razorpay_customer_id and
stripe_subscription_id -> razorpay_subscription_id on the workspaces table.
"""

from alembic import op

revision = "017_stripe_to_razorpay"
down_revision = "016_add_missing_message_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename columns
    op.alter_column("workspaces", "stripe_customer_id", new_column_name="razorpay_customer_id")
    op.alter_column("workspaces", "stripe_subscription_id", new_column_name="razorpay_subscription_id")

    # Drop old index if it exists, create new one
    op.drop_index("ix_workspaces_stripe_customer_id", table_name="workspaces", if_exists=True)
    op.create_index("ix_workspaces_razorpay_customer_id", "workspaces", ["razorpay_customer_id"])


def downgrade() -> None:
    op.drop_index("ix_workspaces_razorpay_customer_id", table_name="workspaces", if_exists=True)
    op.create_index("ix_workspaces_stripe_customer_id", "workspaces", ["stripe_customer_id"])

    op.alter_column("workspaces", "razorpay_customer_id", new_column_name="stripe_customer_id")
    op.alter_column("workspaces", "razorpay_subscription_id", new_column_name="stripe_subscription_id")
