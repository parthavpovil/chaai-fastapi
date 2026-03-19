"""
Document Model
Knowledge base document management
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class Document(Base):
    """Document model for knowledge base files"""
    __tablename__ = "documents"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending | processing | ready | failed
    chunks_count = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, name='{self.name}', status='{self.status}')>"