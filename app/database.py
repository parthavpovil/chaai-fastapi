"""
Database Configuration and Session Management
PostgreSQL with asyncpg driver and SQLAlchemy 2.0 async support
"""
from typing import AsyncGenerator
from sqlalchemy import MetaData
from sqlalchemy.exc import IllegalStateChangeError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool

from app.config import settings

# Create async engine with connection pooling
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL queries in debug mode
    pool_pre_ping=True,   # Verify connections before use
    pool_recycle=3600,    # Recycle connections after 1 hour
    # Use NullPool for development to avoid connection issues
    poolclass=NullPool if settings.DEBUG else None,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Create declarative base with naming convention for constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)
Base = declarative_base(metadata=metadata)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get database session
    Used with FastAPI's Depends() for dependency injection
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        try:
            await session.close()
        except IllegalStateChangeError:
            pass


async def init_db() -> None:
    """
    Initialize database - create all tables
    Used during application startup
    """
    async with engine.begin() as conn:
        # Import all models to ensure they are registered with Base
        from app.models import (
            user, workspace, channel, contact, conversation, message,
            agent, document, document_chunk, usage_counter, 
            platform_setting, tier_change, rate_limit
        )
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close database connections
    Used during application shutdown
    """
    await engine.dispose()