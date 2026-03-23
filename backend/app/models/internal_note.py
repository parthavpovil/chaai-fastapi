"""
InternalNote Model
Agent-only private notes on conversations (not visible to customers)
"""
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class InternalNote(Base):
    """Internal notes written by agents on conversations"""
    __tablename__ = "internal_notes"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="internal_notes")
    agent = relationship("Agent", back_populates="internal_notes")

    def __repr__(self) -> str:
        return f"<InternalNote(id={self.id}, conversation_id={self.conversation_id})>"
