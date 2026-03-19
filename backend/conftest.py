"""
Pytest configuration and fixtures for ChatSaaS Backend tests
"""
import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.config import settings


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create a test database session using SQLite in-memory database
    """
    # Use SQLite in-memory database for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False
    )

    # Enable foreign key enforcement for SQLite (off by default)
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session factory
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    # Create session
    async with async_session() as session:
        yield session
    
    # Clean up
    await engine.dispose()


@pytest.fixture
def mock_db_session():
    """Mock database session for unit tests that don't need real database"""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_settings():
    """Mock settings for testing"""
    return {
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "SECRET_KEY": "test-secret-key",
        "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": 30,
        "STORAGE_PATH": "/tmp/test_storage",
        "DEBUG": True,
        "SUPER_ADMIN_EMAIL": "admin@test.com"
    }


@pytest.fixture
async def postgres_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Create a test database session using the actual PostgreSQL database
    This fixture is used for tests that require PostgreSQL-specific features like pgvector
    """
    # Use the actual PostgreSQL database from settings
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False
    )
    
    # Create session factory
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    # Create session
    async with async_session() as session:
        yield session
        # Rollback any changes made during the test
        await session.rollback()
    
    # Clean up
    await engine.dispose()