"""
Platform Setting Model
Key-value configuration for platform-wide settings
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, func

from app.database import Base


class PlatformSetting(Base):
    """Platform setting model for key-value configuration"""
    __tablename__ = "platform_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<PlatformSetting(key='{self.key}', value='{self.value}')>"