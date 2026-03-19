"""
Tier Change Model
Audit log for workspace tier changes
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class TierChange(Base):
    """Tier change model for audit logging"""
    __tablename__ = "tier_changes"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    from_tier = Column(String, nullable=False)
    to_tier = Column(String, nullable=False)
    changed_by = Column(String, nullable=False)  # admin email or system
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="tier_changes")

    def __repr__(self) -> str:
        return f"<TierChange(workspace_id={self.workspace_id}, from='{self.from_tier}', to='{self.to_tier}')>"