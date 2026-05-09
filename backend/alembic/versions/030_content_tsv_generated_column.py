"""Convert content_tsv to GENERATED ALWAYS AS column

Revision ID: 030_content_tsv_generated_column
Revises: 029_add_workspace_soft_delete
Create Date: 2026-05-07

Changes:
- Drop content_tsv column (and its GIN index) from document_chunks
- Re-add content_tsv as GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
- Recreate GIN index on the new generated column

After this migration, Postgres maintains content_tsv automatically on every
INSERT and UPDATE.  The manual bulk UPDATE in embedding_service is no longer
needed (and would error on a GENERATED ALWAYS column).
"""

from alembic import op

revision = "030_content_tsv_generated_column"
down_revision = "029_add_workspace_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the GIN index first (required before dropping the column).
    op.execute("DROP INDEX IF EXISTS idx_chunks_content_tsv_gin")

    # Drop the manually-maintained column.
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_tsv")

    # Re-add as a server-computed stored column.  Postgres fills it immediately
    # for all existing rows; no data migration script needed.
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )

    # Recreate the GIN index on the generated column.
    op.execute(
        "CREATE INDEX idx_chunks_content_tsv_gin "
        "ON document_chunks USING GIN (content_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_content_tsv_gin")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_tsv")
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN content_tsv tsvector"
    )
    op.execute(
        "CREATE INDEX idx_chunks_content_tsv_gin "
        "ON document_chunks USING GIN (content_tsv)"
    )
