"""
Contact Model
Customer contact management across channels
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB, ARRAY
from sqlalchemy.orm import relationship

from app.database import Base


class Contact(Base):
    """Contact model for customer identification across channels"""
    __tablename__ = "contacts"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    channel_id = Column(PostgresUUID(as_uuid=True), ForeignKey("channels.id"), nullable=False)
    external_id = Column(String, nullable=False)  # platform-specific user ID
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    tags = Column(ARRAY(String), nullable=False, server_default="{}")
    custom_fields = Column(JSONB, nullable=False, default=dict)
    source = Column(String, nullable=True)   # "telegram" | "whatsapp" | "instagram" | "webchat" | "api"
    is_blocked = Column(Boolean, nullable=False, default=False)
    metadata = Column(JSONB, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Broadcast opt-out
    broadcast_opted_out = Column(Boolean, nullable=False, default=False)
    opted_out_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="contacts")
    channel = relationship("Channel", back_populates="contacts")
    conversations = relationship("Conversation", back_populates="contact", cascade="all, delete-orphan")

    # Constraints - unique contact per channel
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel_id", "external_id", name="uq_contact_per_channel"),
    )

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, external_id='{self.external_id}', channel_id={self.channel_id})>"