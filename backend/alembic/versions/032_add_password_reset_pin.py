"""Add password reset PIN fields to users table

Revision ID: 032_add_password_reset_pin
Revises: 031_add_user_email_verification
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = "032_add_password_reset_pin"
down_revision = "031_add_user_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_reset_pin_hash", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_sent_day", sa.Date(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_sent_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "password_reset_attempts")
    op.drop_column("users", "password_reset_sent_count")
    op.drop_column("users", "password_reset_sent_day")
    op.drop_column("users", "password_reset_last_sent_at")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_pin_hash")
