"""
BusinessHours Model
Per-workspace operating hours schedule with timezone support
"""
from uuid import uuid4
from sqlalchemy import Column, String, Integer, Boolean, Time, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class BusinessHours(Base):
    """Business hours schedule — one row per day of week per workspace"""
    __tablename__ = "business_hours"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_of_week = Column(Integer, nullable=False)   # 0=Monday … 6=Sunday
    open_time = Column(Time, nullable=True)          # null when is_closed=True
    close_time = Column(Time, nullable=True)         # null when is_closed=True
    is_closed = Column(Boolean, nullable=False, default=False)
    timezone = Column(String, nullable=False, default="UTC")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workspace = relationship("Workspace", back_populates="business_hours")

    __table_args__ = (
        UniqueConstraint("workspace_id", "day_of_week", name="uq_business_hours_day"),
    )

    def __repr__(self) -> str:
        return f"<BusinessHours(workspace_id={self.workspace_id}, day={self.day_of_week}, closed={self.is_closed})>"
