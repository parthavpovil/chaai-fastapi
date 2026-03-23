"""
APIKey Model
Programmatic access keys for server-to-server API use
"""
from uuid import uuid4
from sqlalchemy import Column, String, Boolean, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class APIKey(Base):
    """API keys for programmatic workspace access"""
    __tablename__ = "api_keys"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True)  # SHA-256 of raw key
    prefix = Column(String, nullable=False)  # First 8 chars of raw key (for display)
    scopes = Column(JSONB, default=list)  # ["read:conversations", "write:messages"]
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, prefix='{self.prefix}', workspace_id={self.workspace_id})>"
