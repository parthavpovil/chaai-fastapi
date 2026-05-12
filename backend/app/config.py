"""
Application Configuration
Environment variables and settings management using Pydantic Settings
"""
import logging
import os
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings

_config_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    APP_URL: str = Field(default="http://localhost:8000", description="Public application base URL — MUST be set via APP_URL env var in production")
    ALLOWED_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080",
            "https://chaai.online",
            "https://admin.chaai.online",
            
        ],
        description="CORS allowed origins"
    )
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/chatsaas",
        description="PostgreSQL database connection URL"
    )
    DB_POOL_SIZE: int = Field(default=10, description="SQLAlchemy async engine pool_size (production)")
    DB_MAX_OVERFLOW: int = Field(default=5, description="SQLAlchemy async engine max_overflow (production)")
    DB_POOL_TIMEOUT: int = Field(default=10, description="Seconds to wait for a pool connection before raising")
    
    # JWT Authentication
    JWT_SECRET_KEY: str = Field(
        min_length=32,
        description="JWT secret key (minimum 32 characters)"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    JWT_EXPIRE_MINUTES: int = Field(default=15, description="Access token expiration in minutes (short-lived)")
    JWT_REFRESH_EXPIRE_DAYS: int = Field(default=7, description="Refresh token expiration in days")
    
    # AI Provider Selection
    AI_PROVIDER: str = Field(
        default="openai",
        pattern="^(google|openai|groq|anthropic)$",
        description="LLM provider: google | openai | groq | anthropic"
    )
    EMBEDDING_PROVIDER: str = Field(
        default="openai",
        pattern="^(google|openai)$",
        description="Embedding provider: google | openai"
    )
    
    # Google AI
    GOOGLE_API_KEY: str = Field(default="", description="Google AI API key")
    
    # OpenAI
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key")
    
    # Groq
    GROQ_API_KEY: str = Field(default="", description="Groq API key")

    # Anthropic (Claude)
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key for Claude models")
    
    # Channel Secrets
    TELEGRAM_SECRET_TOKEN: str = Field(default="", description="Telegram webhook secret token")
    WHATSAPP_APP_SECRET: str = Field(default="", description="WhatsApp app secret")
    INSTAGRAM_APP_SECRET: str = Field(default="", description="Instagram app secret")
    META_VERIFY_TOKEN: str = Field(default="", description="Meta webhook verify token (shared for WhatsApp + Instagram)")

    # Unofficial WhatsApp (Baileys gateway)
    WHATSAPP_GATEWAY_URL: str = Field(default="", description="Baileys WhatsApp gateway base URL")
    WHATSAPP_GATEWAY_API_KEY: str = Field(default="", description="Baileys gateway API key (X-Gateway-Token)")
    WHATSAPP_WEBHOOK_SECRET: str = Field(default="", description="Shared secret for verifying gateway webhook callbacks")
    
    # Email Service (Resend)
    RESEND_API_KEY: str = Field(default="", description="Resend API key")
    RESEND_FROM_EMAIL: str = Field(
        default="alerts@yourdomain.com",
        description="Sender email for transactional emails — MUST be set via RESEND_FROM_EMAIL env var in production"
    )
    RESEND_WEBHOOK_SECRET: str = Field(default="", description="Resend webhook signing secret")
    
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
    
    # Razorpay Billing
    RAZORPAY_KEY_ID: str = Field(default="", description="Razorpay Key ID")
    RAZORPAY_KEY_SECRET: str = Field(default="", description="Razorpay Key Secret")
    RAZORPAY_WEBHOOK_SECRET: str = Field(default="", description="Razorpay webhook signing secret")
    RAZORPAY_PLAN_STARTER: str = Field(default="", description="Razorpay plan_id for Starter tier")
    RAZORPAY_PLAN_GROWTH: str = Field(default="", description="Razorpay plan_id for Growth tier")
    RAZORPAY_PLAN_PRO: str = Field(default="", description="Razorpay plan_id for Pro tier")

    # Cloudflare R2 (S3-compatible object storage for WhatsApp media)
    R2_ACCOUNT_ID: str = Field(default="", description="Cloudflare account ID")
    R2_ACCESS_KEY_ID: str = Field(default="", description="R2 API access key ID")
    R2_SECRET_ACCESS_KEY: str = Field(default="", description="R2 API secret access key")
    R2_BUCKET_NAME: str = Field(default="chaai-media", description="R2 bucket name")
    R2_PUBLIC_DOMAIN: str = Field(default="media.yourdomain.com", description="R2 public CDN domain — MUST be set via R2_PUBLIC_DOMAIN env var in production")

    # Redis (for broadcast queue and pub/sub)
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL (DB 0 — pub/sub)")
    # Separate DB for arq job queue so queue traffic doesn't mix with pub/sub.
    # Defaults to REDIS_URL with /0 replaced by /1 if not explicitly set.
    REDIS_QUEUE_URL: str = Field(default="", description="Redis URL for arq job queue (DB 1). Defaults to REDIS_URL on DB 1.")

    # Observability
    SENTRY_DSN: str = Field(default="", description="Sentry DSN — leave empty to disable Sentry")
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.1, description="Sentry performance traces sample rate (0.0–1.0)")

    # Administration
    SUPER_ADMIN_EMAIL: str = Field(
        default="admin@yourdomain.com",
        description="Super administrator email address — MUST be set via SUPER_ADMIN_EMAIL env var in production"
    )
    
    @property
    def redis_queue_url(self) -> str:
        if self.REDIS_QUEUE_URL:
            return self.REDIS_QUEUE_URL
        # Derive from REDIS_URL: swap the DB number to 1
        base = self.REDIS_URL.rstrip("/")
        # Handle redis://host:port/N and redis://host:port forms
        if "/" in base.split("://", 1)[-1]:
            base = base.rsplit("/", 1)[0]
        return f"{base}/1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Tier configuration as defined in the specification
TIER_LIMITS = {
    "free": {
        "channels": 1,
        "agents": 0,
        "ai_agents": 0,
        "documents_max": 3,
        "monthly_messages": 500,
        "canned_responses": 5,
        "has_assignment_rules": False,
        "has_api_access": False,
        "has_outbound_webhooks": False,
        "has_custom_ai": False,
        "has_conversation_summary": False,
        "has_csat_trends": False,
        "has_export": False,
        "price": 0,
    },
    "starter": {
        "channels": 2,
        "agents": 0,
        "ai_agents": 1,
        "documents_max": 10,
        "monthly_messages": 2000,
        "canned_responses": 10,
        "has_assignment_rules": False,
        "has_api_access": False,
        "has_outbound_webhooks": False,
        "has_custom_ai": False,
        "has_conversation_summary": False,
        "has_csat_trends": False,
        "has_export": False,
        "price": 15,
    },
    "growth": {
        "channels": 4,
        "agents": 0,
        "ai_agents": 3,
        "documents_max": 25,
        "monthly_messages": 10000,
        "canned_responses": 50,
        "has_assignment_rules": False,
        "has_api_access": True,
        "has_outbound_webhooks": True,
        "has_custom_ai": True,
        "has_conversation_summary": True,
        "has_csat_trends": True,
        "has_export": True,
        "price": 29,
    },
    "pro": {
        "channels": 4,
        "agents": 2,
        "ai_agents": 10,
        "documents_max": 100,
        "monthly_messages": 50000,
        "canned_responses": -1,  # unlimited
        "has_assignment_rules": True,
        "has_api_access": True,
        "has_outbound_webhooks": True,
        "has_custom_ai": True,
        "has_conversation_summary": True,
        "has_csat_trends": True,
        "has_export": True,
        "price": 59,
    },
}

# Global settings instance
settings = Settings()

# Warn at startup if placeholder values are still in use
_PLACEHOLDER_CHECKS = [
    ("APP_URL", settings.APP_URL, "http://localhost:8000"),
    ("RESEND_FROM_EMAIL", settings.RESEND_FROM_EMAIL, "yourdomain.com"),
    ("R2_PUBLIC_DOMAIN", settings.R2_PUBLIC_DOMAIN, "yourdomain.com"),
    ("SUPER_ADMIN_EMAIL", settings.SUPER_ADMIN_EMAIL, "yourdomain.com"),
]
for _name, _value, _placeholder_hint in _PLACEHOLDER_CHECKS:
    if _placeholder_hint in _value:
        _config_logger.warning(
            "Config %s is still set to a placeholder value ('%s'). "
            "Set the %s environment variable before deploying to production.",
            _name, _value, _name,
        )