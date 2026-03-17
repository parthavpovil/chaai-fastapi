"""
Document Chunk Model
Vector embeddings for RAG (Retrieval Augmented Generation)
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, func, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
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
    embedding = Column(Vector(3072), nullable=False)  # gemini-embedding-001 dimensions (3072 for Google, 1536 for OpenAI)
    chunk_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="document_chunks")
    document = relationship("Document", back_populates="chunks")

    # Indexes for performance
    __table_args__ = (
        Index("ix_chunks_workspace_embedding", "workspace_id"),
        # HNSW index for vector similarity search will be created in migration
        # CREATE INDEX idx_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops);
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk(id={self.id}, document_id={self.document_id}, chunk_index={self.chunk_index})>"