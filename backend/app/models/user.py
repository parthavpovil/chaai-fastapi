"""
User Model
Authentication and user management
"""
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Date, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    """User model for authentication and workspace ownership"""
    __tablename__ = "users"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    email_verification_pin_hash = Column(String, nullable=True)
    email_verification_expires_at = Column(DateTime(timezone=True), nullable=True)
    email_verification_last_sent_at = Column(DateTime(timezone=True), nullable=True)
    email_verification_sent_day = Column(Date, nullable=True)
    email_verification_sent_count = Column(Integer, default=0, nullable=False)
    email_verification_attempts = Column(Integer, default=0, nullable=False)
    password_reset_pin_hash = Column(String, nullable=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)
    password_reset_last_sent_at = Column(DateTime(timezone=True), nullable=True)
    password_reset_sent_day = Column(Date, nullable=True)
    password_reset_sent_count = Column(Integer, default=0, nullable=False)
    password_reset_attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    owned_workspaces = relationship("Workspace", back_populates="owner", cascade="all, delete-orphan")
    agent_profile = relationship("Agent", back_populates="user", uselist=False)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"