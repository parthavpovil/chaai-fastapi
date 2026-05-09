"""
Pytest configuration and fixtures for ChatSaaS Backend tests
"""
import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.database import Base
from app.config import settings


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_engine():
    """
    Session-scoped engine backed by the DATABASE_URL configured in the environment.

    In CI this is postgresql+asyncpg://... (pgvector/pgvector:pg16 service container).
    Locally developers can set DATABASE_URL to a local Postgres or keep a local
    test database.  The SQLite in-memory shortcut has been removed because it
    masks Postgres-specific ORM behaviour (JSONB operators, tsvector, pgvector).
    """
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async session that rolls back after each test."""
    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_db_session():
    """Mock database session for unit tests that don't need a real database."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_settings():
    """Minimal settings dict for tests that inspect config values."""
    return {
        "DATABASE_URL": settings.DATABASE_URL,
        "SECRET_KEY": "test-secret-key",
        "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": 30,
        "STORAGE_PATH": "/tmp/test_storage",
        "DEBUG": True,
        "SUPER_ADMIN_EMAIL": "admin@test.com",
    }
