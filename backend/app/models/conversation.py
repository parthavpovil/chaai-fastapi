"""
Conversation Model
Customer conversation threading and status management
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, Index, Integer, String, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class Conversation(Base):
    """Conversation model for message threading and status tracking"""
    __tablename__ = "conversations"
    __table_args__ = (
        # Covers the primary list query: filter by workspace, sort by recency.
        Index("ix_conversations_workspace_updated", "workspace_id", "updated_at"),
        # Covers equality-filter queries (e.g. WHERE status = 'escalated').
        # Created in migration 0001; declared here for documentation.
        Index("ix_conversations_workspace_status", "workspace_id", "status"),
        # Recency list using denormalized last_message_at (added in migration
        # 034). Declared here for documentation only.
        Index("ix_conversations_workspace_lastmsg", "workspace_id", "last_message_at"),
    )

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    contact_id = Column(PostgresUUID(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    channel_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ai")  # ai | escalated | agent | resolved
    assigned_agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    escalation_reason = Column(String, nullable=True)  # explicit | implicit
    meta = Column("metadata", JSONB, default=dict, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Denormalized counters maintained at every Message INSERT site (see
    # message_processor.create_message, escalation_router, conversation_manager).
    # Backfill of pre-existing rows happens in migration 034.
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, nullable=False, server_default="0", default=0)

    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="conversations")
    contact = relationship("Contact", back_populates="conversations")
    assigned_agent = relationship("Agent", back_populates="assigned_conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    internal_notes = relationship("InternalNote", back_populates="conversation", cascade="all, delete-orphan")
    csat_rating = relationship("CSATRating", back_populates="conversation", uselist=False)

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, status='{self.status}', contact_id={self.contact_id})>"