"""
Unit tests for Admin Service
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from app.services.admin_service import AdminService
from app.config import settings


class TestAdminService:
    """Test cases for AdminService"""
    
    def test_is_super_admin_valid_email(self):
        """Test super admin validation with valid email"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Test with exact match
        assert admin_service.is_super_admin(settings.SUPER_ADMIN_EMAIL) is True
        
        # Test with case insensitive match
        assert admin_service.is_super_admin(settings.SUPER_ADMIN_EMAIL.upper()) is True
        assert admin_service.is_super_admin(settings.SUPER_ADMIN_EMAIL.lower()) is True
    
    def test_is_super_admin_invalid_email(self):
        """Test super admin validation with invalid email"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Test with different email
        assert admin_service.is_super_admin("user@example.com") is False
        assert admin_service.is_super_admin("") is False
        assert admin_service.is_super_admin("admin@different.com") is False
    
    @pytest.mark.asyncio
    async def test_suspend_user_unauthorized(self):
        """Test suspend user with unauthorized email"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        user_id = uuid4()
        unauthorized_email = "user@example.com"
        
        with pytest.raises(ValueError, match="Unauthorized: Only super admin can suspend users"):
            await admin_service.suspend_user(user_id, unauthorized_email)
    
    @pytest.mark.asyncio
    async def test_unsuspend_user_unauthorized(self):
        """Test unsuspend user with unauthorized email"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        user_id = uuid4()
        unauthorized_email = "user@example.com"
        
        with pytest.raises(ValueError, match="Unauthorized: Only super admin can unsuspend users"):
            await admin_service.unsuspend_user(user_id, unauthorized_email)
    
    @pytest.mark.asyncio
    async def test_change_workspace_tier_unauthorized(self):
        """Test change workspace tier with unauthorized email"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        workspace_id = uuid4()
        unauthorized_email = "user@example.com"
        
        with pytest.raises(ValueError, match="Unauthorized: Only super admin can change tiers"):
            await admin_service.change_workspace_tier(
                workspace_id, "pro", unauthorized_email
            )
    
    @pytest.mark.asyncio
    async def test_change_workspace_tier_invalid_tier(self):
        """Test change workspace tier with invalid tier"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        workspace_id = uuid4()
        admin_email = settings.SUPER_ADMIN_EMAIL
        
        with pytest.raises(ValueError, match="Invalid tier"):
            await admin_service.change_workspace_tier(
                workspace_id, "invalid_tier", admin_email
            )
    
    def test_platform_overview_basic_structure(self):
        """Test that platform overview method exists and has correct signature"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Just verify the method exists and can be called
        assert hasattr(admin_service, 'get_platform_overview')
        assert callable(admin_service.get_platform_overview)


if __name__ == "__main__":
    pytest.main([__file__])