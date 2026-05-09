"""
Tests for admin tier management and analytics functionality
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from app.services.admin_service import AdminService
from app.models.user import User
from app.models.workspace import Workspace
from app.models.usage_counter import UsageCounter
from app.models.conversation import Conversation


class TestAdminTierManagement:
    """Test admin tier management and analytics functionality"""
    
    @pytest.mark.asyncio
    async def test_delete_workspace_success(self):
        """Test successful workspace deletion with correct name confirmation"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Mock workspace
        workspace = MagicMock()
        workspace.id = uuid4()
        workspace.name = "Test Workspace"
        
        # Mock database query
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = workspace
        db_mock.execute.return_value = result_mock
        
        # Test deletion with correct admin email
        result = await admin_service.delete_workspace(
            workspace_id=workspace.id,
            confirmation_name="Test Workspace",
            admin_email="admin@yourdomain.com"  # Use the default admin email
        )
        
        assert result is True
        # Workspace is soft-deleted (deleted_at set) rather than hard-deleted.
        assert workspace.deleted_at is not None
        db_mock.delete.assert_not_called()
        db_mock.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_delete_workspace_wrong_name(self):
        """Test workspace deletion fails with wrong name confirmation"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Mock workspace
        workspace = MagicMock()
        workspace.id = uuid4()
        workspace.name = "Test Workspace"
        
        # Mock database query
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = workspace
        db_mock.execute.return_value = result_mock
        
        # Try to delete with wrong name
        with pytest.raises(ValueError, match="Workspace name confirmation does not match"):
            await admin_service.delete_workspace(
                workspace_id=workspace.id,
                confirmation_name="Wrong Name",
                admin_email="admin@yourdomain.com"
            )
    
    @pytest.mark.asyncio
    async def test_delete_workspace_unauthorized(self):
        """Test workspace deletion fails for non-admin user"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Try to delete as non-admin
        with pytest.raises(ValueError, match="Unauthorized: Only super admin can delete workspaces"):
            await admin_service.delete_workspace(
                workspace_id=uuid4(),
                confirmation_name="Test Workspace",
                admin_email="notadmin@test.com"
            )
    
    @pytest.mark.asyncio
    async def test_delete_workspace_not_found(self):
        """Test workspace deletion fails for non-existent workspace"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Mock empty result
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db_mock.execute.return_value = result_mock
        
        # Try to delete non-existent workspace
        with pytest.raises(ValueError, match="Workspace not found"):
            await admin_service.delete_workspace(
                workspace_id=uuid4(),
                confirmation_name="Test Workspace",
                admin_email="admin@yourdomain.com"
            )
    
    @pytest.mark.asyncio
    async def test_analytics_dashboard_basic_structure(self):
        """Test analytics dashboard returns correct structure with mocked data"""
        db_mock = AsyncMock()
        admin_service = AdminService(db_mock)
        
        # Mock all database calls to return empty results
        mock_result = MagicMock()
        mock_result.__iter__ = lambda x: iter([])
        mock_result.scalar.return_value = 0
        db_mock.execute.return_value = mock_result
        
        # Get analytics dashboard
        analytics = await admin_service.get_analytics_dashboard()
        
        # Verify structure
        assert "message_volume" in analytics
        assert "signup_trends" in analytics
        assert "escalation_statistics" in analytics
        
        # Verify message volume structure
        message_volume = analytics["message_volume"]
        assert "monthly_data" in message_volume
        assert "current_month" in message_volume
        assert "trend_months" in message_volume
        
        # Verify signup trends structure
        signup_trends = analytics["signup_trends"]
        assert "monthly_data" in signup_trends
        assert "current_month" in signup_trends
        assert "trend_months" in signup_trends
        
        # Verify escalation statistics structure
        escalation_stats = analytics["escalation_statistics"]
        assert "total_escalations" in escalation_stats
        assert "total_conversations" in escalation_stats
        assert "escalation_rate" in escalation_stats
        
        # Verify escalation rate calculation with zero conversations
        assert escalation_stats["escalation_rate"] == 0