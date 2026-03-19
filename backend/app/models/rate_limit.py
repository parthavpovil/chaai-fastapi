"""
Rate Limit Model
Database-backed rate limiting for WebChat sessions
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID

from app.database import Base


class RateLimit(Base):
    """Rate limit model for database-backed rate limiting"""
    __tablename__ = "rate_limits"

    key = Column(String, primary_key=True)  # format: "webchat:{session_token}"
    count = Column(Integer, default=1, nullable=False)
    reset_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<RateLimit(key='{self.key}', count={self.count})>"