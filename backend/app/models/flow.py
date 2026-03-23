"""
Flow and ConversationFlowState Models
Interactive message flow builder for WhatsApp automation
"""
from uuid import uuid4
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB, ARRAY
from sqlalchemy.orm import relationship

from app.database import Base


class Flow(Base):
    """Flow model — defines a multi-step interactive message sequence"""
    __tablename__ = "flows"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(100), nullable=False)
    trigger_keywords = Column(ARRAY(String), nullable=True)  # e.g. ["book", "appointment"]
    trigger_type = Column(String(20), nullable=True)         # keyword | manual | ai_detected
    is_active = Column(Boolean, default=True)
    steps = Column(JSONB, nullable=False)                    # full step tree
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="flows")
    flow_states = relationship("ConversationFlowState", back_populates="flow")

    def __repr__(self) -> str:
        return f"<Flow(id={self.id}, name='{self.name}')>"


class ConversationFlowState(Base):
    """Tracks a conversation's progress through a flow"""
    __tablename__ = "conversation_flow_states"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, unique=True)
    flow_id = Column(PostgresUUID(as_uuid=True), ForeignKey("flows.id"), nullable=False)
    current_step_id = Column(String(50), nullable=False)
    collected_data = Column(JSONB, default=dict)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    abandoned_at = Column(DateTime(timezone=True), nullable=True)

    flow = relationship("Flow", back_populates="flow_states")
    conversation = relationship("Conversation")

    def __repr__(self) -> str:
        return f"<ConversationFlowState(conversation_id={self.conversation_id}, step='{self.current_step_id}')>"
