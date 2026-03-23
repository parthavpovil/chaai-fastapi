"""
AIFeedback Model
Thumbs up/down feedback on AI-generated responses
"""
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class AIFeedback(Base):
    """Agent/owner feedback on AI message quality"""
    __tablename__ = "ai_feedback"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(PostgresUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    rating = Column(String, nullable=False)  # "positive" | "negative"
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    message = relationship("Message", back_populates="ai_feedback")

    # One feedback per message
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_ai_feedback_message"),
    )

    def __repr__(self) -> str:
        return f"<AIFeedback(id={self.id}, message_id={self.message_id}, rating='{self.rating}')>"
