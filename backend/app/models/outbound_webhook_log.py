"""
OutboundWebhookLog Model
Delivery attempt history for outbound webhook events
"""
from uuid import uuid4
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class OutboundWebhookLog(Base):
    """Records each delivery attempt for an outbound webhook"""
    __tablename__ = "outbound_webhook_logs"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    webhook_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("outbound_webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    response_status_code = Column(Integer, nullable=True)   # null on network failure
    response_body = Column(Text, nullable=True)              # truncated to 2000 chars
    duration_ms = Column(Integer, nullable=True)
    is_success = Column(Boolean, nullable=False)
    delivered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    webhook = relationship("OutboundWebhook", back_populates="logs")
    workspace = relationship("Workspace", back_populates="outbound_webhook_logs")

    def __repr__(self) -> str:
        return f"<OutboundWebhookLog(id={self.id}, webhook_id={self.webhook_id}, is_success={self.is_success})>"
