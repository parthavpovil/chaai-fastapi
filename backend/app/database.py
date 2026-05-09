"""
Database Configuration and Session Management
PostgreSQL with asyncpg driver and SQLAlchemy 2.0 async support
"""
from typing import AsyncGenerator
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import NullPool

from app.config import settings

# NullPool (DEBUG): one connection per request, no pool — safe for hot reload.
# QueuePool (production): explicit pool_size + max_overflow avoids exhausting
# Postgres max_connections when multiple Gunicorn workers share the same DB.
_pool_kwargs: dict = (
    {"poolclass": NullPool}
    if settings.DEBUG
    else {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
    }
)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_recycle=3600,
    **_pool_kwargs,
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
        except Exception:
            pass


async def init_db() -> None:
    """
    Initialize database connection - enables pgvector extension.
    Migrations are run via entrypoint.sh before workers start.
    """
    # Enable pgvector extension (required for VECTOR columns)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def close_db() -> None:
    """
    Close database connections
    Used during application shutdown
    """
    await engine.dispose()