"""
CannedResponse Model
Saved reply templates for agents to speed up responses
"""
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class CannedResponse(Base):
    """Pre-written response templates for agents"""
    __tablename__ = "canned_responses"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    shortcut = Column(String, nullable=True)  # e.g. "/greeting" — unique per workspace
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="canned_responses")

    # Constraints
    __table_args__ = (
        UniqueConstraint("workspace_id", "shortcut", name="uq_canned_response_shortcut"),
    )

    def __repr__(self) -> str:
        return f"<CannedResponse(id={self.id}, name='{self.name}', workspace_id={self.workspace_id})>"
