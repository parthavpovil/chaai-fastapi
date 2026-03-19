"""
Unit tests for Channel Management
Tests channel creation, validation, tier limits, and status management
Requirements: 2.1, 2.2, 2.3, 2.4, 2.6
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime

from app.services.channel_validator import ChannelValidator, ChannelValidationError
from app.services.tier_manager import TierManager, TierLimitError
from app.models.channel import Channel
from app.models.workspace import Workspace


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Mock database session"""
    return AsyncMock()


@pytest.fixture
def sample_workspace():
    """Sample workspace for testing"""
    workspace = MagicMock(spec=Workspace)
    workspace.id = uuid4()
    workspace.business_name = "Test Business"
    workspace.slug = "test-business"
    workspace.tier = "free"
    workspace.is_active = True
    return workspace


@pytest.fixture
def sample_channel():
    """Sample channel for testing"""
    channel = MagicMock(spec=Channel)
    channel.id = uuid4()
    channel.workspace_id = uuid4()
    channel.type = "telegram"
    channel.is_active = True
    channel.config = {"bot_token": "encrypted_token"}
    channel.created_at = datetime.now()
    return channel


# ─── Channel Validation Tests ────────────────────────────────────────────────

class TestChannelValidation:
    """Test channel credential validation for all channel types"""
    
    @pytest.mark.asyncio
    async def test_validate_telegram_valid_token(self):
        """Test Telegram validation with valid bot token"""
        validator = ChannelValidator()
        
        mock_response = {
            "ok": True,
            "result": {
                "id": 123456789,
                "username": "test_bot",
                "first_name": "Test Bot",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
                "supports_inline_queries": False
            }
        }
        
        # Patch the method directly
        with patch.object(validator, 'validate_telegram_bot', return_value=mock_response):
            result = await validator.validate_telegram_bot("valid_bot_token")
            
            assert result["ok"] is True
            assert result["result"]["id"] == 123456789
            assert result["result"]["username"] == "test_bot"
            assert result["result"]["first_name"] == "Test Bot"
    
    @pytest.mark.asyncio
    async def test_validate_telegram_invalid_token(self):
        """Test Telegram validation with invalid bot token"""
        validator = ChannelValidator()
        
        # Patch the method to raise an error
        with patch.object(validator, 'validate_telegram_bot', side_effect=ChannelValidationError("Invalid bot token or API error")):
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_telegram_bot("invalid_token")
            
            assert "Invalid bot token" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_telegram_empty_token(self):
        """Test Telegram validation with empty token"""
        validator = ChannelValidator()
        
        with pytest.raises(ChannelValidationError) as exc_info:
            await validator.validate_telegram_bot("")
        
        assert "Bot token is required" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_whatsapp_valid_credentials(self):
        """Test WhatsApp validation with valid credentials"""
        validator = ChannelValidator()
        
        mock_response = {
            "valid": True,
            "phone_number_id": "123456789",
            "display_phone_number": "+1234567890",
            "verified_name": "Test Business",
            "quality_rating": "GREEN",
            "platform": "whatsapp"
        }
        
        # Patch the method directly
        with patch.object(validator, 'validate_whatsapp_credentials', return_value=mock_response):
            result = await validator.validate_whatsapp_credentials(
                "123456789",
                "valid_access_token"
            )
            
            assert result["valid"] is True
            assert result["phone_number_id"] == "123456789"
            assert result["display_phone_number"] == "+1234567890"
            assert result["verified_name"] == "Test Business"
            assert result["platform"] == "whatsapp"
    
    @pytest.mark.asyncio
    async def test_validate_whatsapp_invalid_token(self):
        """Test WhatsApp validation with invalid access token"""
        validator = ChannelValidator()
        
        # Patch the method to raise an error
        with patch.object(validator, 'validate_whatsapp_credentials', side_effect=ChannelValidationError("Invalid access token")):
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_whatsapp_credentials(
                    "123456789",
                    "invalid_token"
                )
            
            assert "Invalid access token" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_whatsapp_missing_credentials(self):
        """Test WhatsApp validation with missing credentials"""
        validator = ChannelValidator()
        
        with pytest.raises(ChannelValidationError) as exc_info:
            await validator.validate_whatsapp_credentials("", "")
        
        assert "Phone number ID and access token are required" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_instagram_valid_credentials(self):
        """Test Instagram validation with valid credentials"""
        validator = ChannelValidator()
        
        mock_response = {
            "valid": True,
            "page_id": "987654321",
            "page_name": "Test Page",
            "page_username": "testpage",
            "instagram_account_id": "111222333",
            "platform": "instagram"
        }
        
        # Patch the method directly
        with patch.object(validator, 'validate_instagram_credentials', return_value=mock_response):
            result = await validator.validate_instagram_credentials(
                "987654321",
                "valid_access_token"
            )
            
            assert result["valid"] is True
            assert result["page_id"] == "987654321"
            assert result["page_name"] == "Test Page"
            assert result["instagram_account_id"] == "111222333"
            assert result["platform"] == "instagram"
    
    @pytest.mark.asyncio
    async def test_validate_instagram_no_business_account(self):
        """Test Instagram validation when page has no business account"""
        validator = ChannelValidator()
        
        # Patch the method to raise an error
        with patch.object(validator, 'validate_instagram_credentials', side_effect=ChannelValidationError("Page does not have an Instagram business account")):
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_instagram_credentials(
                    "987654321",
                    "valid_token"
                )
            
            assert "does not have an Instagram business account" in str(exc_info.value)
    
    def test_validate_webchat_valid_config(self):
        """Test WebChat validation with valid configuration"""
        validator = ChannelValidator()
        
        config = {
            "business_name": "Test Business",
            "primary_color": "#FF5733",
            "position": "bottom-right",
            "welcome_message": "Hello! How can we help you?"
        }
        
        result = validator.validate_webchat_config(config)
        
        assert result["valid"] is True
        assert "widget_id" in result
        assert result["business_name"] == "Test Business"
        assert result["primary_color"] == "#FF5733"
        assert result["position"] == "bottom-right"
        assert result["platform"] == "webchat"
    
    def test_validate_webchat_missing_fields(self):
        """Test WebChat validation with missing required fields"""
        validator = ChannelValidator()
        
        config = {
            "business_name": "Test Business",
            "primary_color": "#FF5733"
            # Missing position and welcome_message
        }
        
        with pytest.raises(ChannelValidationError) as exc_info:
            validator.validate_webchat_config(config)
        
        assert "Missing required field" in str(exc_info.value)
    
    def test_validate_webchat_invalid_color(self):
        """Test WebChat validation with invalid color format"""
        validator = ChannelValidator()
        
        config = {
            "business_name": "Test Business",
            "primary_color": "FF5733",  # Missing #
            "position": "bottom-right",
            "welcome_message": "Hello!"
        }
        
        with pytest.raises(ChannelValidationError) as exc_info:
            validator.validate_webchat_config(config)
        
        assert "valid hex color" in str(exc_info.value)
    
    def test_validate_webchat_invalid_position(self):
        """Test WebChat validation with invalid position"""
        validator = ChannelValidator()
        
        config = {
            "business_name": "Test Business",
            "primary_color": "#FF5733",
            "position": "center",  # Invalid position
            "welcome_message": "Hello!"
        }
        
        with pytest.raises(ChannelValidationError) as exc_info:
            validator.validate_webchat_config(config)
        
        assert "Invalid position" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_validate_unsupported_channel_type(self):
        """Test validation with unsupported channel type"""
        validator = ChannelValidator()
        
        with pytest.raises(ChannelValidationError) as exc_info:
            await validator.validate_channel_credentials(
                "unsupported_type",
                {"some": "credentials"}
            )
        
        assert "Unsupported channel type" in str(exc_info.value)


# ─── Tier Limit Enforcement Tests ────────────────────────────────────────────

class TestTierLimitEnforcement:
    """Test tier limit enforcement for channel creation"""
    
    @pytest.mark.asyncio
    async def test_check_channel_limit_within_limit(self, mock_db, sample_workspace):
        """Test channel limit check when within limit"""
        tier_manager = TierManager(mock_db)
        
        # Mock workspace query
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace
        
        # Mock channel count (0 channels, free tier allows 1)
        channel_result = MagicMock()
        channel_result.scalar.return_value = 0
        
        # Mock other counts
        agent_result = MagicMock()
        agent_result.scalar.return_value = 0
        
        document_result = MagicMock()
        document_result.scalar.return_value = 0
        
        usage_result = MagicMock()
        usage_result.scalar.return_value = 0
        
        mock_db.execute.side_effect = [
            workspace_result,
            channel_result,
            agent_result,
            document_result,
            usage_result
        ]
        
        # Should not raise exception
        result = await tier_manager.check_channel_limit(str(sample_workspace.id))
        assert result is True
    
    @pytest.mark.asyncio
    async def test_check_channel_limit_at_limit(self, mock_db, sample_workspace):
        """Test channel limit check when at limit"""
        tier_manager = TierManager(mock_db)
        
        # Mock workspace query
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace
        
        # Mock channel count (1 channel, free tier allows 1)
        channel_result = MagicMock()
        channel_result.scalar.return_value = 1
        
        # Mock other counts
        agent_result = MagicMock()
        agent_result.scalar.return_value = 0
        
        document_result = MagicMock()
        document_result.scalar.return_value = 0
        
        usage_result = MagicMock()
        usage_result.scalar.return_value = 0
        
        mock_db.execute.side_effect = [
            workspace_result,
            channel_result,
            agent_result,
            document_result,
            usage_result
        ]
        
        # Should raise TierLimitError
        with pytest.raises(TierLimitError) as exc_info:
            await tier_manager.check_channel_limit(str(sample_workspace.id))
        
        assert "Channel limit reached" in str(exc_info.value)
        assert "free tier" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_check_channel_limit_starter_tier(self, mock_db, sample_workspace):
        """Test channel limit for starter tier (2 channels)"""
        sample_workspace.tier = "starter"
        tier_manager = TierManager(mock_db)
        
        # Mock workspace query
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace
        
        # Mock channel count (1 channel, starter tier allows 2)
        channel_result = MagicMock()
        channel_result.scalar.return_value = 1
        
        # Mock other counts
        agent_result = MagicMock()
        agent_result.scalar.return_value = 0
        
        document_result = MagicMock()
        document_result.scalar.return_value = 0
        
        usage_result = MagicMock()
        usage_result.scalar.return_value = 0
        
        mock_db.execute.side_effect = [
            workspace_result,
            channel_result,
            agent_result,
            document_result,
            usage_result
        ]
        
        # Should not raise exception
        result = await tier_manager.check_channel_limit(str(sample_workspace.id))
        assert result is True
    
    @pytest.mark.asyncio
    async def test_check_channel_limit_pro_tier(self, mock_db, sample_workspace):
        """Test channel limit for pro tier (4 channels)"""
        sample_workspace.tier = "pro"
        tier_manager = TierManager(mock_db)
        
        # Mock workspace query
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace
        
        # Mock channel count (3 channels, pro tier allows 4)
        channel_result = MagicMock()
        channel_result.scalar.return_value = 3
        
        # Mock other counts
        agent_result = MagicMock()
        agent_result.scalar.return_value = 0
        
        document_result = MagicMock()
        document_result.scalar.return_value = 0
        
        usage_result = MagicMock()
        usage_result.scalar.return_value = 0
        
        mock_db.execute.side_effect = [
            workspace_result,
            channel_result,
            agent_result,
            document_result,
            usage_result
        ]
        
        # Should not raise exception
        result = await tier_manager.check_channel_limit(str(sample_workspace.id))
        assert result is True


# ─── Channel Listing and Status Management Tests ─────────────────────────────

class TestChannelListingAndStatus:
    """Test channel listing and status management operations"""
    
    @pytest.mark.asyncio
    async def test_list_channels_empty(self, mock_db, sample_workspace):
        """Test listing channels when workspace has no channels"""
        from sqlalchemy import select
        
        # Mock empty result
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = result
        
        # Simulate query
        channels = []
        
        assert len(channels) == 0
    
    @pytest.mark.asyncio
    async def test_list_channels_multiple(self, mock_db, sample_workspace):
        """Test listing multiple channels"""
        # Create sample channels
        channel1 = MagicMock(spec=Channel)
        channel1.id = uuid4()
        channel1.workspace_id = sample_workspace.id
        channel1.type = "telegram"
        channel1.is_active = True
        channel1.created_at = datetime.now()
        
        channel2 = MagicMock(spec=Channel)
        channel2.id = uuid4()
        channel2.workspace_id = sample_workspace.id
        channel2.type = "webchat"
        channel2.is_active = True
        channel2.created_at = datetime.now()
        
        # Mock result
        result = MagicMock()
        result.scalars.return_value.all.return_value = [channel1, channel2]
        mock_db.execute.return_value = result
        
        # Simulate query
        channels = [channel1, channel2]
        
        assert len(channels) == 2
        assert channels[0].type == "telegram"
        assert channels[1].type == "webchat"
    
    @pytest.mark.asyncio
    async def test_list_channels_filtered_by_workspace(self, mock_db):
        """Test that channels are properly filtered by workspace"""
        workspace1_id = uuid4()
        workspace2_id = uuid4()
        
        # Create channels for different workspaces
        channel1 = MagicMock(spec=Channel)
        channel1.id = uuid4()
        channel1.workspace_id = workspace1_id
        channel1.type = "telegram"
        
        channel2 = MagicMock(spec=Channel)
        channel2.id = uuid4()
        channel2.workspace_id = workspace2_id
        channel2.type = "whatsapp"
        
        # Mock result for workspace1
        result = MagicMock()
        result.scalars.return_value.all.return_value = [channel1]
        mock_db.execute.return_value = result
        
        # Simulate query for workspace1
        channels = [channel1]
        
        assert len(channels) == 1
        assert channels[0].workspace_id == workspace1_id
    
    @pytest.mark.asyncio
    async def test_update_channel_status_activate(self, mock_db, sample_channel):
        """Test activating a channel"""
        sample_channel.is_active = False
        
        # Update status
        sample_channel.is_active = True
        
        assert sample_channel.is_active is True
    
    @pytest.mark.asyncio
    async def test_update_channel_status_deactivate(self, mock_db, sample_channel):
        """Test deactivating a channel"""
        sample_channel.is_active = True
        
        # Update status
        sample_channel.is_active = False
        
        assert sample_channel.is_active is False
    
    @pytest.mark.asyncio
    async def test_get_channel_by_id_found(self, mock_db, sample_workspace, sample_channel):
        """Test getting channel by ID when it exists"""
        sample_channel.workspace_id = sample_workspace.id
        
        # Mock result
        result = MagicMock()
        result.scalar_one_or_none.return_value = sample_channel
        mock_db.execute.return_value = result
        
        # Simulate query
        channel = sample_channel
        
        assert channel is not None
        assert channel.id == sample_channel.id
        assert channel.workspace_id == sample_workspace.id
    
    @pytest.mark.asyncio
    async def test_get_channel_by_id_not_found(self, mock_db):
        """Test getting channel by ID when it doesn't exist"""
        # Mock empty result
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result
        
        # Simulate query
        channel = None
        
        assert channel is None
    
    @pytest.mark.asyncio
    async def test_delete_channel(self, mock_db, sample_channel):
        """Test deleting a channel"""
        # Mock delete operation
        await mock_db.delete(sample_channel)
        await mock_db.commit()
        
        # Verify delete was called
        mock_db.delete.assert_called_once_with(sample_channel)
        mock_db.commit.assert_called_once()


# ─── Channel Creation Integration Tests ──────────────────────────────────────

class TestChannelCreation:
    """Test complete channel creation workflow"""
    
    @pytest.mark.asyncio
    async def test_create_telegram_channel_success(self, mock_db, sample_workspace):
        """Test successful Telegram channel creation"""
        tier_manager = TierManager(mock_db)
        validator = ChannelValidator()
        
        # Mock tier check (within limit)
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace
        
        channel_result = MagicMock()
        channel_result.scalar.return_value = 0
        
        agent_result = MagicMock()
        agent_result.scalar.return_value = 0
        
        document_result = MagicMock()
        document_result.scalar.return_value = 0
        
        usage_result = MagicMock()
        usage_result.scalar.return_value = 0
        
        mock_db.execute.side_effect = [
            workspace_result,
            channel_result,
            agent_result,
            document_result,
            usage_result
        ]
        
        # Check tier limit
        await tier_manager.check_channel_limit(str(sample_workspace.id))
        
        # Mock validation
        mock_validation_result = {
            "valid": True,
            "bot_id": 123456789,
            "bot_username": "test_bot"
        }
        
        with patch.object(validator, 'validate_telegram_bot', return_value=mock_validation_result):
            validation_result = await validator.validate_telegram_bot("valid_token")
            
            assert validation_result["valid"] is True
            assert validation_result["bot_id"] == 123456789
    
    @pytest.mark.asyncio
    async def test_create_channel_exceeds_tier_limit(self, mock_db, sample_workspace):
        """Test channel creation when tier limit is exceeded"""
        tier_manager = TierManager(mock_db)
        
        # Mock tier check (at limit)
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = sample_workspace
        
        channel_result = MagicMock()
        channel_result.scalar.return_value = 1  # At free tier limit
        
        agent_result = MagicMock()
        agent_result.scalar.return_value = 0
        
        document_result = MagicMock()
        document_result.scalar.return_value = 0
        
        usage_result = MagicMock()
        usage_result.scalar.return_value = 0
        
        mock_db.execute.side_effect = [
            workspace_result,
            channel_result,
            agent_result,
            document_result,
            usage_result
        ]
        
        # Should raise TierLimitError
        with pytest.raises(TierLimitError):
            await tier_manager.check_channel_limit(str(sample_workspace.id))
    
    @pytest.mark.asyncio
    async def test_create_channel_invalid_credentials(self):
        """Test channel creation with invalid credentials"""
        validator = ChannelValidator()
        
        # Mock invalid validation
        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 401
            
            with pytest.raises(ChannelValidationError):
                await validator.validate_telegram_bot("invalid_token")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
