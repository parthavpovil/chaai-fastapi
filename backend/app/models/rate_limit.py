"""
Rate Limit Model
Database-backed rate limiting for WebChat sessions
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, ARRAY, TIMESTAMP

from app.database import Base


class RateLimit(Base):
    """Rate limit model for database-backed rate limiting"""
    __tablename__ = "rate_limits"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier = Column(String, nullable=False, index=True)
    limit_type = Column(String, nullable=False)
    workspace_id = Column(PostgresUUID(as_uuid=True), nullable=True, index=True)
    request_timestamps = Column(ARRAY(TIMESTAMP(timezone=True)), default=list, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<RateLimit(identifier='{self.identifier}', type='{self.limit_type}')>"
