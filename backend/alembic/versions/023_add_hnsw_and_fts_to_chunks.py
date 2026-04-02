"""Add HNSW index, content_tsv column and GIN index to document_chunks

Revision ID: 023_hnsw_fts_chunks
Revises: 022_add_routing_settings
Create Date: 2026-04-02

Changes:
- Add content_tsv tsvector column for BM25 / full-text search
- Backfill content_tsv for all existing rows
- Create HNSW index on embedding (vector_cosine_ops, m=16, ef_construction=64)
- Create GIN index on content_tsv
"""

from alembic import op

revision = "023_hnsw_fts_chunks"
down_revision = "022_add_routing_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add content_tsv column
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS content_tsv tsvector"
    )

    # 2. Backfill existing rows
    op.execute(
        "UPDATE document_chunks "
        "SET content_tsv = to_tsvector('english', content) "
        "WHERE content_tsv IS NULL"
    )

    # 3. Create indexes inside the Alembic transaction (no CONCURRENTLY).
    #    Regular CREATE INDEX is faster for migrations; the brief table lock
    #    is acceptable during a controlled deployment.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv_gin "
        "ON document_chunks USING GIN (content_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_content_tsv_gin")
    op.execute("DROP INDEX IF EXISTS idx_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_tsv"
    )
