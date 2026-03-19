"""
Channel Model
Communication channel management (Telegram, WhatsApp, Instagram, WebChat)
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Channel(Base):
    """Channel model for communication platform integrations"""
    __tablename__ = "channels"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    type = Column(String, nullable=False)  # telegram | whatsapp | instagram | webchat
    is_active = Column(Boolean, default=True, nullable=False)
    config = Column(JSONB, default=dict)  # encrypted credentials stored here
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="channels")
    contacts = relationship("Contact", back_populates="channel", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        UniqueConstraint("workspace_id", "type", name="uq_workspace_channel_type"),
    )

    def __repr__(self) -> str:
        return f"<Channel(id={self.id}, type='{self.type}', workspace_id={self.workspace_id})>"