"""Add content_tsv, GIN index, and HNSW index to document_chunks

Revision ID: 023_hnsw_fts_chunks
Revises: 022_add_routing_settings
Create Date: 2026-04-02

Changes:
- Truncate document_chunks and documents (existing data not needed)
- Add content_tsv tsvector column for BM25 / full-text search
- Create GIN index on content_tsv
- Create HNSW index on embedding (vector_cosine_ops)

All operations complete in milliseconds because the table is empty after truncation.
New documents must be re-uploaded after deployment.
"""

from alembic import op

revision = "023_hnsw_fts_chunks"
down_revision = "022_add_routing_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Clear existing data so index builds are instant (empty table = no work)
    op.execute("TRUNCATE TABLE document_chunks CASCADE")
    op.execute("TRUNCATE TABLE documents CASCADE")

    # Add content_tsv column
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS content_tsv tsvector"
    )

    # GIN index for BM25 full-text search (instant on empty table)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv_gin "
        "ON document_chunks USING GIN (content_tsv)"
    )

    # HNSW index for fast vector search (instant on empty table)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_content_tsv_gin")
    op.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_tsv"
    )
