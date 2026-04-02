"""
Document Chunk Model
Vector embeddings for RAG (Retrieval Augmented Generation)
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, Integer, Text, DateTime, func, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB, TSVECTOR
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.database import Base


class DocumentChunk(Base):
    """Document chunk model with vector embeddings for similarity search"""
    __tablename__ = "document_chunks"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)  # denormalized for efficient querying
    document_id = Column(PostgresUUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)  # text-embedding-3-small (OpenAI, 1536 dims)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=True)
    start_char = Column(Integer, nullable=True)
    end_char = Column(Integer, nullable=True)
    chunk_metadata = Column("metadata", JSONB, nullable=True)
    content_tsv = Column(TSVECTOR, nullable=True)  # populated via bulk UPDATE in embedding_service
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="document_chunks")
    document = relationship("Document", back_populates="chunks")

    # Indexes for performance
    __table_args__ = (
        Index("ix_chunks_workspace_embedding", "workspace_id"),
        # HNSW index: idx_chunks_embedding_hnsw (created in migration 023)
        # GIN index:  idx_chunks_content_tsv_gin  (created in migration 023)
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk(id={self.id}, document_id={self.document_id}, chunk_index={self.chunk_index})>"