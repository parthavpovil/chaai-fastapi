"""Add content_tsv, GIN index, and HNSW index to document_chunks

Revision ID: 023_hnsw_fts_chunks
Revises: 022_add_routing_settings
Create Date: 2026-04-02

Changes:
- Remove documents that have no embedded chunks (incompatible with new indexes)
- Add content_tsv tsvector column for BM25 / full-text search
- Create GIN index on content_tsv
- Create HNSW index on embedding (vector_cosine_ops)

Note: the original upgrade() used TRUNCATE TABLE which would destroy all data
if this migration were ever re-applied (recovery, downgrade+upgrade, branch
rebase).  Replaced with a conditional DELETE that only removes documents
without embeddings — safe to re-run on a server that already has live data.
content_tsv is superseded by migration 030 (GENERATED ALWAYS AS column).
"""

from alembic import op

revision = "023_hnsw_fts_chunks"
down_revision = "022_add_routing_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard: only clear data if the table still has rows from before the HNSW
    # column was added (i.e. chunks without embeddings that are incompatible
    # with the new index).  On any server where this migration has already run,
    # the tables are empty and the DELETE is instant.  On a recovery or branch
    # scenario the delete is selective rather than a blind TRUNCATE, so a
    # mistaken re-run cannot destroy live data silently.
    #
    # TRUNCATE was used originally because it is faster on a truly empty table;
    # DELETE ... WHERE TRUE is equivalent but is not a DDL statement and will
    # not auto-commit, keeping it inside Alembic's transaction.
    op.execute(
        "DELETE FROM documents "
        "WHERE id NOT IN ("
        "  SELECT DISTINCT document_id FROM document_chunks "
        "  WHERE embedding IS NOT NULL"
        ")"
    )

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
