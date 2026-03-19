"""
Message Model
Individual messages within conversations
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, func, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Message(Base):
    """Message model for individual messages in conversations"""
    __tablename__ = "messages"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)  # customer | ai | agent
    content = Column(Text, nullable=False)
    channel_type = Column(String, nullable=False)
    external_message_id = Column(String, nullable=True)  # for deduplication
    extra_data = Column("metadata", JSONB, default=dict)  # Map to 'metadata' column in DB
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    # Indexes for performance
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        # Unique constraint for external message deduplication (only when not null)
        # This will be created as a partial unique index in migration
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role='{self.role}', conversation_id={self.conversation_id})>"