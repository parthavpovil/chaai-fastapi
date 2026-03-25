"""
Workspace Model
Multi-tenant workspace management
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Workspace(Base):
    """Workspace model for multi-tenant isolation"""
    __tablename__ = "workspaces"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id = Column(PostgresUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    tier = Column(String, nullable=False, default="free")
    fallback_msg = Column(String, default="Sorry, I could not find an answer. Our team will get back to you.")
    alert_email = Column(String, nullable=True)
    agents_enabled = Column(Boolean, default=False)
    subscription_notes = Column(Text, nullable=True)
    tier_changed_at = Column(DateTime(timezone=True), nullable=True)
    tier_changed_by = Column(String, nullable=True)
    meta = Column("metadata", JSONB, default=dict, nullable=True)  # workspace-level settings (AI config, etc.)
    outside_hours_message = Column(Text, nullable=True)
    outside_hours_behavior = Column(String, nullable=True, default="inform_and_continue")
    escalation_keywords = Column(JSONB, nullable=True)  # None = use built-in defaults
    escalation_sensitivity = Column(String, nullable=False, default="medium")
    razorpay_customer_id = Column(String, nullable=True)
    razorpay_subscription_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    owner = relationship("User", back_populates="owned_workspaces")
    channels = relationship("Channel", back_populates="workspace", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="workspace", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="workspace", cascade="all, delete-orphan")
    agents = relationship("Agent", back_populates="workspace", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="workspace", cascade="all, delete-orphan")
    document_chunks = relationship("DocumentChunk", back_populates="workspace", cascade="all, delete-orphan")
    usage_counters = relationship("UsageCounter", back_populates="workspace", cascade="all, delete-orphan")
    tier_changes = relationship("TierChange", back_populates="workspace", cascade="all, delete-orphan")
    canned_responses = relationship("CannedResponse", back_populates="workspace", cascade="all, delete-orphan")
    assignment_rules = relationship("AssignmentRule", back_populates="workspace", cascade="all, delete-orphan")
    outbound_webhooks = relationship("OutboundWebhook", back_populates="workspace", cascade="all, delete-orphan")
    outbound_webhook_logs = relationship("OutboundWebhookLog", back_populates="workspace", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="workspace", cascade="all, delete-orphan")
    csat_ratings = relationship("CSATRating", back_populates="workspace", cascade="all, delete-orphan")
    business_hours = relationship("BusinessHours", back_populates="workspace", cascade="all, delete-orphan")
    flows = relationship("Flow", back_populates="workspace", cascade="all, delete-orphan")
    whatsapp_templates = relationship("WhatsAppTemplate", back_populates="workspace", cascade="all, delete-orphan")
    broadcasts = relationship("Broadcast", back_populates="workspace", cascade="all, delete-orphan")
    ai_agents = relationship("AIAgent", back_populates="workspace", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, name='{self.name}', slug='{self.slug}')>"