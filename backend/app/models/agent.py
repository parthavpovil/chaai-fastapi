"""
Agent Model
Human agent management and invitation system
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class Agent(Base):
    """Agent model for human support representatives"""
    __tablename__ = "agents"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(PostgresUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # null until invitation accepted
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    invitation_token = Column(String, nullable=True)
    invitation_expires_at = Column(DateTime(timezone=True), nullable=True)
    invitation_accepted_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="offline")  # online | offline | busy
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="agents")
    user = relationship("User", back_populates="agent_profile")
    assigned_conversations = relationship("Conversation", back_populates="assigned_agent")
    internal_notes = relationship("InternalNote", back_populates="agent")
    targeted_rules = relationship("AssignmentRule", back_populates="target_agent")

    # Constraints - unique email per workspace
    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_agent_workspace_email"),
    )

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, email='{self.email}', workspace_id={self.workspace_id})>"