"""
EmailLog Model
Tracks email events received from Resend webhooks (sent, delivered, bounced, etc.)
"""
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class EmailLog(Base):
    """Records each email event received via Resend webhook"""
    __tablename__ = "email_logs"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email_id = Column(String, nullable=False, index=True)   # Resend email ID
    event_type = Column(String, nullable=False)              # sent/delivered/bounced/complained/opened/clicked/delayed
    recipient = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    extra_data = Column(JSONB, nullable=False, default=dict) # full event payload from Resend
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="email_logs")

    def __repr__(self) -> str:
        return f"<EmailLog(id={self.id}, email_id={self.email_id}, event_type={self.event_type})>"
