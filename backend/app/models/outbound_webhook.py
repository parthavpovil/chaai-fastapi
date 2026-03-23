"""
OutboundWebhook Model
Workspace event subscriptions — sends signed HTTP POSTs on key events
"""
from uuid import uuid4
from sqlalchemy import Column, String, Integer, Boolean, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class OutboundWebhook(Base):
    """Outbound webhook subscriptions for workspace events"""
    __tablename__ = "outbound_webhooks"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False)
    # events JSONB list: ["conversation.created", "message.received", "conversation.escalated", "conversation.resolved"]
    events = Column(JSONB, nullable=False, default=list)
    secret = Column(String, nullable=False)  # HMAC signing secret (plaintext, stored only here)
    is_active = Column(Boolean, default=True, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="outbound_webhooks")
    logs = relationship("OutboundWebhookLog", back_populates="webhook", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<OutboundWebhook(id={self.id}, url='{self.url}', workspace_id={self.workspace_id})>"
