#!/usr/bin/env python3
"""
Manual integration test for admin tier management endpoints
Run this script to test the new endpoints manually
"""
import asyncio
import os
from uuid import uuid4
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from main import app
from app.config import settings
from app.models.user import User
from app.models.workspace import Workspace
from app.services.auth_service import AuthService
from app.database import Base


async def create_test_data():
    """Create test data for integration testing"""
    # Use test database
    engine = create_async_engine(settings.TEST_DATABASE_URL)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Create admin user
        auth_service = AuthService(session)
        admin_user = await auth_service.create_user(
            email=settings.SUPER_ADMIN_EMAIL,
            password="admin123",
            business_name="Admin Workspace"
        )
        
        # Create test workspace
        test_workspace = Workspace(
            owner_id=admin_user.id,
            name="Test Workspace for Deletion",
            slug="test-workspace-deletion",
            tier="free"
        )
        session.add(test_workspace)
        await session.commit()
        
        return admin_user, test_workspace


async def test_admin_endpoints():
    """Test the admin endpoints with proper authentication"""
    print("Creating test data...")
    admin_user, test_workspace = await create_test_data()
    
    # Create JWT token for admin user
    from app.services.auth_service import create_access_token
    admin_token = create_access_token(data={"sub": admin_user.email, "workspace_id": str(admin_user.workspace_id)})
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        print("\n=== Testing Analytics Dashboard ===")
        
        # Test analytics endpoint
        response = await client.get(
            "/api/admin/analytics",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        print(f"Analytics endpoint status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print("Analytics data structure:")
            print(f"- Message volume keys: {list(data['message_volume'].keys())}")
            print(f"- Signup trends keys: {list(data['signup_trends'].keys())}")
            print(f"- Escalation stats keys: {list(data['escalation_statistics'].keys())}")
            print(f"- Escalation rate: {data['escalation_statistics']['escalation_rate']}%")
        else:
            print(f"Error: {response.json()}")
        
        print("\n=== Testing Workspace Deletion ===")
        
        # Test workspace deletion with wrong name (should fail)
        response = await client.request(
            "DELETE",
            "/api/admin/workspaces/delete",
            json={
                "workspace_id": str(test_workspace.id),
                "confirmation_name": "Wrong Name"
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        print(f"Delete with wrong name status: {response.status_code}")
        if response.status_code != 200:
            print(f"Expected error: {response.json()['detail']}")
        
        # Test workspace deletion with correct name (should succeed)
        response = await client.request(
            "DELETE",
            "/api/admin/workspaces/delete",
            json={
                "workspace_id": str(test_workspace.id),
                "confirmation_name": "Test Workspace for Deletion"
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        print(f"Delete with correct name status: {response.status_code}")
        if response.status_code == 200:
            print(f"Success: {response.json()['message']}")
        else:
            print(f"Error: {response.json()}")
        
        print("\n=== Testing Non-Admin Access ===")
        
        # Test with invalid token (should fail)
        response = await client.get(
            "/api/admin/analytics",
            headers={"Authorization": "Bearer invalid_token"}
        )
        
        print(f"Invalid token status: {response.status_code}")
        print(f"Error: {response.json()['detail']}")


if __name__ == "__main__":
    # Set test environment
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_integration.db"
    os.environ["TEST_DATABASE_URL"] = "sqlite+aiosqlite:///./test_integration.db"
    
    asyncio.run(test_admin_endpoints())
    print("\nIntegration test completed!")