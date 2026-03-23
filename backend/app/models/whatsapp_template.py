"""
WhatsApp Template Model
Stores WhatsApp message templates for broadcast and re-engagement
"""
from uuid import uuid4
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class WhatsAppTemplate(Base):
    """WhatsApp message template — submitted to Meta for approval"""
    __tablename__ = "whatsapp_templates"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(100), nullable=False)          # lowercase_underscore only
    category = Column(String(20), nullable=False)        # MARKETING | UTILITY | AUTHENTICATION
    language = Column(String(10), nullable=False)        # "en" | "hi" | "ml" | "ta"
    status = Column(String(20), default="draft")         # draft|pending|approved|rejected
    rejection_reason = Column(Text, nullable=True)
    header_type = Column(String(20), nullable=True)      # none|text|image|video|document
    header_content = Column(Text, nullable=True)
    body = Column(Text, nullable=False)                  # "Hi {{1}}, your order {{2}}..."
    footer = Column(Text, nullable=True)
    buttons = Column(JSONB, nullable=True)
    meta_template_id = Column(String(100), nullable=True)  # ID returned by Meta after submission
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship("Workspace", back_populates="whatsapp_templates")

    def __repr__(self) -> str:
        return f"<WhatsAppTemplate(id={self.id}, name='{self.name}', status='{self.status}')>"
