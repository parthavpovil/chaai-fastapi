"""
AI Agent Models
SQLAlchemy ORM models for the AI Agent feature
"""
from uuid import uuid4
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Float, Integer,
    ForeignKey, func, Numeric, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class AIAgent(Base):
    """AI Agent configuration — distinct from human Agent model"""
    __tablename__ = "ai_agents"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    system_prompt = Column(Text, nullable=False)
    persona_name = Column(String(50), nullable=True)
    persona_tone = Column(String(50), default="friendly")
    first_message = Column(Text, nullable=True)
    escalation_trigger = Column(String(50), default="low_confidence")
    escalation_message = Column(Text, default="Let me connect you with a team member.")
    confidence_threshold = Column(Float, default=0.7)
    max_turns = Column(Integer, default=10)
    token_budget = Column(Integer, default=8000)
    is_active = Column(Boolean, default=True)
    is_draft = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="ai_agents")
    tools = relationship("AIAgentTool", back_populates="agent", cascade="all, delete-orphan")
    guardrails = relationship("AIAgentGuardrail", back_populates="agent", cascade="all, delete-orphan")
    channel_assignments = relationship("AIAgentChannelAssignment", back_populates="agent", cascade="all, delete-orphan")
    conversations = relationship("AIAgentConversation", back_populates="agent")


class AIAgentTool(Base):
    """External HTTP tool callable by an AI agent"""
    __tablename__ = "ai_agent_tools"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("ai_agents.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)          # snake_case — used in LLM tool schema
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)           # LLM reads this to decide when to call
    method = Column(String(10), default="GET")
    endpoint_url = Column(Text, nullable=False)
    headers = Column(JSONB, default=dict)               # encrypted via encryption.py
    body_template = Column(JSONB, nullable=True)
    parameters = Column(JSONB, nullable=False, default=list)
    # [{"name": "order_id", "type": "string", "required": true, "description": "..."}]
    response_path = Column(Text, nullable=True)
    requires_confirmation = Column(Boolean, default=False)
    is_read_only = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent = relationship("AIAgent", back_populates="tools")


class AIAgentGuardrail(Base):
    """Safety guardrail rules for an AI agent"""
    __tablename__ = "ai_agent_guardrails"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("ai_agents.id", ondelete="CASCADE"), nullable=False)
    rule_type = Column(String(30), nullable=False)  # forbidden_topic | forbidden_action | required_escalation
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent = relationship("AIAgent", back_populates="guardrails")


class AIAgentChannelAssignment(Base):
    """Maps an AI agent to a channel"""
    __tablename__ = "ai_agent_channel_assignments"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("ai_agents.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(PostgresUUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent = relationship("AIAgent", back_populates="channel_assignments")
    channel = relationship("Channel")

    __table_args__ = (
        UniqueConstraint("channel_id", "agent_id", name="uq_channel_agent"),
    )


class AIAgentConversation(Base):
    """Tracks an AI agent's engagement with a conversation"""
    __tablename__ = "ai_agent_conversations"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("ai_agents.id"), nullable=False)
    conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    status = Column(String(20), default="active")  # active | escalated | resolved | abandoned
    turn_count = Column(Integer, default=0)
    escalation_reason = Column(Text, nullable=True)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent = relationship("AIAgent", back_populates="conversations")
    conversation = relationship("Conversation")
    token_logs = relationship("AIAgentTokenLog", back_populates="agent_conversation")


class AIAgentTokenLog(Base):
    """Per-call token usage log for AI agent interactions"""
    __tablename__ = "ai_agent_token_log"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("ai_agents.id"), nullable=True)
    agent_conversation_id = Column(PostgresUUID(as_uuid=True), ForeignKey("ai_agent_conversations.id"), nullable=True)
    model = Column(String(50), nullable=False)
    call_type = Column(String(30), nullable=False)  # tool_selection | response_generation | escalation_check
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    total_cost_usd = Column(Numeric(10, 8), nullable=False)
    tool_name = Column(String(100), nullable=True)
    tool_latency_ms = Column(Integer, nullable=True)
    tool_success = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent_conversation = relationship("AIAgentConversation", back_populates="token_logs")
