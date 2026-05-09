"""
Message Model
Individual messages within conversations
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, func, ForeignKey, UniqueConstraint, Index, Integer, Float
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Message(Base):
    """Message model for individual messages in conversations"""
    __tablename__ = "messages"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)  # customer | assistant | agent | owner
    content = Column(Text, nullable=True)  # nullable for pure media messages
    channel_type = Column(String, nullable=False)
    external_message_id = Column(String, nullable=True)  # for deduplication
    extra_data = Column("metadata", JSONB, default=dict)  # Map to 'metadata' column in DB
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Message type: text | image | video | audio | document | location | contacts | sticker | reaction | interactive
    msg_type = Column("message_type", String, nullable=True, default="text")

    # Media fields (populated when msg_type is image/video/audio/document/sticker)
    media_url = Column(String, nullable=True)
    media_mime_type = Column(String, nullable=True)
    media_filename = Column(String, nullable=True)
    media_size = Column(Integer, nullable=True)

    # Location fields (populated when msg_type is location)
    location_lat = Column(Float, nullable=True)
    location_lng = Column(Float, nullable=True)
    location_name = Column(String, nullable=True)

    # Delivery tracking (populated for outbound messages)
    whatsapp_msg_id = Column("whatsapp_message_id", String, nullable=True, index=True)
    delivery_status = Column(String, nullable=True)   # sent | delivered | read | failed
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    failed_reason = Column(String, nullable=True)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    ai_feedback = relationship("AIFeedback", back_populates="message", uselist=False)

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        # Partial unique index — prevents duplicate inbound messages from carrier retries.
        # Scoped to conversation_id because Telegram IDs are per-chat integers and
        # would collide across workspaces under a global unique index.
        # Created via migration 028; declared here for documentation.
        Index(
            "ix_messages_external_id_unique",
            "conversation_id",
            "external_message_id",
            unique=True,
            postgresql_where="external_message_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role='{self.role}', conversation_id={self.conversation_id})>"