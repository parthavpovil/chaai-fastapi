"""
Broadcast and BroadcastRecipient Models
Manages WhatsApp broadcast campaigns
"""
from uuid import uuid4
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Broadcast(Base):
    """Broadcast campaign — sends a template message to a filtered audience"""
    __tablename__ = "broadcasts"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(100), nullable=False)
    template_id = Column(PostgresUUID(as_uuid=True), ForeignKey("whatsapp_templates.id"), nullable=False)
    variable_mapping = Column(JSONB, nullable=True)     # {"{{1}}": "contact.name", "{{2}}": "static:40% off"}
    audience_type = Column(String(20), nullable=False)  # all | tag | manual
    audience_filter = Column(JSONB, nullable=True)      # {"tags": ["vip"]}
    recipient_count = Column(Integer, nullable=True)
    status = Column(String(20), default="draft")        # draft|scheduled|queued|sending|sent|cancelled
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship("Workspace", back_populates="broadcasts")
    template = relationship("WhatsAppTemplate")
    recipients = relationship("BroadcastRecipient", back_populates="broadcast")

    def __repr__(self) -> str:
        return f"<Broadcast(id={self.id}, name='{self.name}', status='{self.status}')>"


class BroadcastRecipient(Base):
    """Per-contact delivery record for a broadcast"""
    __tablename__ = "broadcast_recipients"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    broadcast_id = Column(PostgresUUID(as_uuid=True), ForeignKey("broadcasts.id"), nullable=False)
    contact_id = Column(PostgresUUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    phone = Column(String(20), nullable=False)           # E.164 format
    variable_values = Column(JSONB, nullable=True)       # resolved per-contact variables
    status = Column(String(20), default="pending")       # pending|sent|delivered|read|failed
    whatsapp_message_id = Column(String(100), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    failed_reason = Column(Text, nullable=True)

    broadcast = relationship("Broadcast", back_populates="recipients")

    def __repr__(self) -> str:
        return f"<BroadcastRecipient(broadcast_id={self.broadcast_id}, phone='{self.phone}', status='{self.status}')>"
