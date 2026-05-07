"""
Usage Counter Model
Monthly usage tracking for tier limits
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, func, ForeignKey, UniqueConstraint, Numeric
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class UsageCounter(Base):
    """Usage counter model for monthly usage tracking"""
    __tablename__ = "usage_counters"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(PostgresUUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    month = Column(String, nullable=False)  # format: "2026-03"
    messages_sent = Column(Integer, default=0, nullable=False)
    tokens_used = Column(BigInteger, default=0, nullable=False)
    total_cost_usd = Column(Numeric(12, 8), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="usage_counters")

    # Constraints - unique counter per workspace per month
    __table_args__ = (
        UniqueConstraint("workspace_id", "month", name="uq_usage_workspace_month"),
    )

    def __repr__(self) -> str:
        return f"<UsageCounter(workspace_id={self.workspace_id}, month='{self.month}', messages={self.messages_sent})>"