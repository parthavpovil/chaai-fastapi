"""
AssignmentRule Model
Automatic conversation routing rules (round-robin, keyword-based, etc.)
"""
from uuid import uuid4
from sqlalchemy import Column, String, Integer, Boolean, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class AssignmentRule(Base):
    """Rules for automatically assigning conversations to agents"""
    __tablename__ = "assignment_rules"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=100)  # lower = higher priority
    # conditions JSONB: {"keywords": ["billing"], "channel_type": "whatsapp"}
    conditions = Column(JSONB, default=dict)
    # action: "round_robin" | "specific_agent" | "least_loaded"
    action = Column(String, nullable=False, default="round_robin")
    target_agent_id = Column(PostgresUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="assignment_rules")
    target_agent = relationship("Agent", back_populates="targeted_rules")

    def __repr__(self) -> str:
        return f"<AssignmentRule(id={self.id}, name='{self.name}', action='{self.action}')>"
