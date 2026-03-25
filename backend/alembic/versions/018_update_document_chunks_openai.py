"""update document_chunks for OpenAI embeddings

Revision ID: 018_update_document_chunks_openai
Revises: 017_stripe_to_razorpay
Create Date: 2026-03-25

Changes:
- Drop and recreate embedding column as vector(1536) for OpenAI text-embedding-3-small
- Add token_count, start_char, end_char, metadata columns
- Truncates existing chunk data since 3072-dim embeddings are incompatible with 1536-dim
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "018_update_document_chunks_openai"
down_revision = "017_stripe_to_razorpay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clear existing chunks — 3072-dim embeddings are incompatible with 1536-dim
    op.execute("DELETE FROM document_chunks")

    # Drop old embedding column and recreate at 1536 dims
    op.drop_column("document_chunks", "embedding")
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(1536) NOT NULL DEFAULT array_fill(0, ARRAY[1536])::vector")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding DROP DEFAULT")

    # Add missing columns
    op.add_column("document_chunks", sa.Column("token_count", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("start_char", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("end_char", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("metadata", JSONB(), nullable=True))

    # Mark any documents as pending re-embedding
    op.execute("UPDATE documents SET status = 'pending' WHERE status = 'completed'")


def downgrade() -> None:
    op.drop_column("document_chunks", "metadata")
    op.drop_column("document_chunks", "end_char")
    op.drop_column("document_chunks", "start_char")
    op.drop_column("document_chunks", "token_count")

    op.execute("DELETE FROM document_chunks")
    op.drop_column("document_chunks", "embedding")
    op.execute("ALTER TABLE document_chunks ADD COLUMN embedding vector(3072) NOT NULL DEFAULT array_fill(0, ARRAY[3072])::vector")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding DROP DEFAULT")
