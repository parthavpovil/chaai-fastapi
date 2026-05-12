"""Add user email verification fields

Revision ID: 031_add_user_email_verification
Revises: 030_content_tsv_generated_column
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "031_add_user_email_verification"
down_revision = "030_content_tsv_generated_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_pin_hash", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_sent_day", sa.Date(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_sent_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_attempts", sa.Integer(), nullable=False, server_default="0"),
    )

    op.alter_column("users", "email_verified", server_default=sa.false())


def downgrade() -> None:
    op.drop_column("users", "email_verification_attempts")
    op.drop_column("users", "email_verification_sent_count")
    op.drop_column("users", "email_verification_sent_day")
    op.drop_column("users", "email_verification_last_sent_at")
    op.drop_column("users", "email_verification_expires_at")
    op.drop_column("users", "email_verification_pin_hash")
    op.drop_column("users", "email_verified")
