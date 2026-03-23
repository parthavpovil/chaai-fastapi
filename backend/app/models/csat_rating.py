"""
CSATRating Model
Customer satisfaction ratings submitted after conversation resolution
"""
from uuid import uuid4
from sqlalchemy import Column, Integer, Text, DateTime, func, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class CSATRating(Base):
    """Customer satisfaction rating — one per resolved conversation"""
    __tablename__ = "csat_ratings"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one rating per conversation
    )
    workspace_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_csat_rating_range"),
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="csat_rating")
    workspace = relationship("Workspace", back_populates="csat_ratings")

    def __repr__(self) -> str:
        return f"<CSATRating(id={self.id}, conversation_id={self.conversation_id}, rating={self.rating})>"
