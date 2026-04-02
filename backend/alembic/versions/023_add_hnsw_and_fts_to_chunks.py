"""Add content_tsv column and GIN index to document_chunks

Revision ID: 023_hnsw_fts_chunks
Revises: 022_add_routing_settings
Create Date: 2026-04-02

Changes:
- Add content_tsv tsvector column for BM25 / full-text search
- Create GIN index on content_tsv

Both operations are instant: ADD COLUMN is O(1) metadata DDL, and the GIN
index has nothing to build because existing rows have content_tsv = NULL
(GIN skips NULLs). New chunks get content_tsv populated by the application.

NOTE: The HNSW vector index must be created manually after deployment because
it indexes the existing embedding column and takes several minutes:

  docker exec -it chatsaas-postgres psql -U <user> -d <db> -c \
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_embedding_hnsw \
     ON document_chunks USING hnsw (embedding vector_cosine_ops) \
     WITH (m = 16, ef_construction = 64);"
"""

from alembic import op

revision = "023_hnsw_fts_chunks"
down_revision = "022_add_routing_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN IF NOT EXISTS content_tsv tsvector"
    )
    # Fast: GIN skips NULL rows, so this is instant on existing data
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
