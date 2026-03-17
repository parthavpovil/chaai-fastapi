import pytest
from app.models import User
from uuid import uuid4

pytestmark = pytest.mark.asyncio

async def test_fixture_debug(db_session):
    """Debug test to see if db_session fixture works"""
    print(f"db_session type: {type(db_session)}")
    print(f"db_session: {db_session}")
    
    # Try to use it
    user = User(
        id=uuid4(),
        email="test@example.com",
        hashed_password="hashed",
        is_active=True
    )
    db_session.add(user)
    await db_session.commit()
    print("Success!")