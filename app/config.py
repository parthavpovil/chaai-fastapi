"""
Application Configuration
Environment variables and settings management using Pydantic Settings
"""
import os
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    APP_URL: str = Field(default="http://localhost:8000", description="Application base URL")
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="CORS allowed origins"
    )
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/chatsaas",
        description="PostgreSQL database connection URL"
    )
    
    # JWT Authentication
    JWT_SECRET_KEY: str = Field(
        min_length=32,
        description="JWT secret key (minimum 32 characters)"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    JWT_EXPIRE_MINUTES: int = Field(default=10080, description="JWT token expiration in minutes (7 days)")
    
    # AI Provider Selection
    AI_PROVIDER: str = Field(
        default="google",
        pattern="^(google|openai|groq)$",
        description="LLM provider: google | openai | groq"
    )
    EMBEDDING_PROVIDER: str = Field(
        default="google",
        pattern="^(google|openai)$",
        description="Embedding provider: google | openai"
    )
    
    # Google AI
    GOOGLE_API_KEY: str = Field(default="", description="Google AI API key")
    
    # OpenAI
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key")
    
    # Groq
    GROQ_API_KEY: str = Field(default="", description="Groq API key")
    
    # Channel Secrets
    TELEGRAM_SECRET_TOKEN: str = Field(default="", description="Telegram webhook secret token")
    WHATSAPP_APP_SECRET: str = Field(default="", description="WhatsApp app secret")
    INSTAGRAM_APP_SECRET: str = Field(default="", description="Instagram app secret")
    
    # Email Service (Resend)
    RESEND_API_KEY: str = Field(default="", description="Resend API key")
    RESEND_FROM_EMAIL: str = Field(
        default="alerts@yourdomain.com",
        description="Default sender email address"
    )
    
    # File Storage
    STORAGE_PATH: str = Field(
        default="/var/chatsaas/storage",
        description="Local file storage path"
    )
    
    # Security
    ENCRYPTION_KEY: str = Field(
        min_length=64,
        max_length=64,
        description="32-byte encryption key as hex string (64 characters)"
    )
    PROCESS_SECRET: str = Field(
        min_length=32,
        description="Process secret for internal API calls"
    )
    
    # Administration
    SUPER_ADMIN_EMAIL: str = Field(
        default="admin@yourdomain.com",
        description="Super administrator email address"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Tier configuration as defined in the specification
TIER_LIMITS = {
    "free": {
        "channels": 1,
        "agents": 0,
        "documents_max": 3,
        "monthly_messages": 500,
        "price": 0,
    },
    "starter": {
        "channels": 2,
        "agents": 0,
        "documents_max": 10,
        "monthly_messages": 2000,
        "price": 15,
    },
    "growth": {
        "channels": 4,
        "agents": 0,
        "documents_max": 25,
        "monthly_messages": 10000,
        "price": 29,
    },
    "pro": {
        "channels": 4,
        "agents": 2,
        "documents_max": 100,
        "monthly_messages": 50000,
        "price": 59,
    },
}

# Global settings instance
settings = Settings()