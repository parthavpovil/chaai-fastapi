"""
Property-Based Test for Channel Connection Validation
Feature: chatsaas-backend, Property 4: Channel Connection Validation

Tests that channel connections are properly validated for all channel types:
- Telegram: Bot token validation via Telegram API
- WhatsApp: Credential validation via Meta API
- Instagram: Page access token validation via Meta API
- WebChat: Widget ID generation and configuration validation

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
from hypothesis.strategies import composite
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any
import aiohttp

from app.services.channel_validator import (
    ChannelValidator,
    ChannelValidationError,
    validate_channel_connection
)


# ─── Helper Functions ──────────────────────────────────────────────────────────

def create_aiohttp_mock(status: int, json_response: dict):
    """
    Create a properly configured aiohttp ClientSession mock
    
    Args:
        status: HTTP status code
        json_response: JSON response data
    
    Returns:
        Configured mock for aiohttp.ClientSession
    """
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_response)
    
    # Create async context manager for session.get()
    mock_get_cm = MagicMock()
    mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_get_cm.__aexit__ = AsyncMock(return_value=None)
    
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_get_cm)
    
    # Create async context manager for ClientSession()
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=None)
    
    return mock_session_cm


# ─── Hypothesis Strategies ────────────────────────────────────────────────────

@composite
def telegram_credentials(draw, valid: bool = True):
    """Generate Telegram bot credentials"""
    if valid:
        # Valid bot token format: <bot_id>:<token>
        bot_id = draw(st.integers(min_value=100000000, max_value=999999999))
        token = draw(st.text(
            min_size=35, 
            max_size=35,
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))
        ))
        return {"bot_token": f"{bot_id}:{token}"}
    else:
        # Invalid credentials
        return {"bot_token": draw(st.sampled_from([
            "",  # Empty token
            "invalid",  # Too short
            "123",  # Missing colon separator
            None  # None value
        ]))}


@composite
def whatsapp_credentials(draw, valid: bool = True):
    """Generate WhatsApp Business credentials"""
    if valid:
        phone_number_id = draw(st.integers(min_value=100000000000000, max_value=999999999999999))
        access_token = draw(st.text(
            min_size=50,
            max_size=200,
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))
        ))
        return {
            "phone_number_id": str(phone_number_id),
            "access_token": access_token
        }
    else:
        return draw(st.sampled_from([
            {"phone_number_id": "", "access_token": "valid_token"},  # Empty phone ID
            {"phone_number_id": "123", "access_token": ""},  # Empty token
            {"phone_number_id": None, "access_token": "token"},  # None phone ID
            {},  # Missing fields
        ]))


@composite
def instagram_credentials(draw, valid: bool = True):
    """Generate Instagram page credentials"""
    if valid:
        page_id = draw(st.integers(min_value=100000000000000, max_value=999999999999999))
        access_token = draw(st.text(
            min_size=50,
            max_size=200,
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))
        ))
        return {
            "page_id": str(page_id),
            "access_token": access_token
        }
    else:
        return draw(st.sampled_from([
            {"page_id": "", "access_token": "valid_token"},  # Empty page ID
            {"page_id": "123", "access_token": ""},  # Empty token
            {"page_id": None, "access_token": "token"},  # None page ID
            {},  # Missing fields
        ]))


@composite
def webchat_config(draw, valid: bool = True):
    """Generate WebChat configuration"""
    if valid:
        business_name = draw(st.text(min_size=1, max_size=100))
        primary_color = draw(st.sampled_from([
            "#FF5733", "#3498DB", "#2ECC71", "#F39C12", "#9B59B6", "#1ABC9C"
        ]))
        position = draw(st.sampled_from([
            "bottom-right", "bottom-left", "top-right", "top-left"
        ]))
        welcome_message = draw(st.text(min_size=1, max_size=500))
        
        return {
            "business_name": business_name,
            "primary_color": primary_color,
            "position": position,
            "welcome_message": welcome_message
        }
    else:
        return draw(st.sampled_from([
            {"business_name": "", "primary_color": "#FF5733", "position": "bottom-right", "welcome_message": "Hi"},
            {"business_name": "Test", "primary_color": "invalid", "position": "bottom-right", "welcome_message": "Hi"},
            {"business_name": "Test", "primary_color": "#FF5733", "position": "invalid", "welcome_message": "Hi"},
            {"business_name": "Test", "primary_color": "#FF5733", "position": "bottom-right", "welcome_message": ""},
            {},  # Missing all fields
        ]))


# ─── Property Tests ────────────────────────────────────────────────────────────

class TestChannelConnectionValidation:
    """
    Property 4: Channel Connection Validation
    
    For any channel type (Telegram, WhatsApp, Instagram, WebChat), connecting with 
    valid credentials should result in successful validation and webhook configuration, 
    while invalid credentials should be rejected with descriptive errors.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """
    
    @given(credentials=telegram_credentials(valid=True))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_telegram_valid_credentials_succeed(self, credentials):
        """
        Test that valid Telegram bot tokens are successfully validated
        Requirement 2.1: Validate bot token via Telegram API and register webhook URL
        """
        validator = ChannelValidator()
        
        # Mock successful Telegram API response
        mock_response = {
            "ok": True,
            "result": {
                "id": 123456789,
                "username": "test_bot",
                "first_name": "Test Bot",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
                "supports_inline_queries": True
            }
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
            
            result = await validator.validate_telegram_bot(credentials["bot_token"])
            
            # Verify successful validation
            assert result["valid"] is True
            assert "bot_id" in result
            assert "bot_username" in result
            assert result["bot_username"] == "test_bot"
    
    @given(credentials=telegram_credentials(valid=False))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_telegram_invalid_credentials_rejected(self, credentials):
        """
        Test that invalid Telegram bot tokens are rejected with descriptive errors
        Requirement 2.1: Validate bot token via Telegram API
        """
        validator = ChannelValidator()
        
        # Test empty or None tokens
        if not credentials.get("bot_token"):
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_telegram_bot(credentials["bot_token"])
            assert "required" in str(exc_info.value).lower()
            return
        
        # Mock failed Telegram API response
        mock_response = {
            "ok": False,
            "description": "Unauthorized"
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = create_aiohttp_mock(401, mock_response)
            
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_telegram_bot(credentials["bot_token"])
            
            # Verify descriptive error message
            assert len(str(exc_info.value)) > 0

    
    @given(credentials=whatsapp_credentials(valid=True))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_whatsapp_valid_credentials_succeed(self, credentials):
        """
        Test that valid WhatsApp Business credentials are successfully validated
        Requirement 2.2: Validate credentials and configure webhook with Meta API
        """
        validator = ChannelValidator()
        
        # Mock successful Meta API response
        mock_response = {
            "id": credentials["phone_number_id"],
            "display_phone_number": "+1234567890",
            "verified_name": "Test Business",
            "quality_rating": "GREEN"
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
            
            result = await validator.validate_whatsapp_credentials(
                credentials["phone_number_id"],
                credentials["access_token"]
            )
            
            # Verify successful validation
            assert result["valid"] is True
            assert result["platform"] == "whatsapp"
            assert "phone_number_id" in result
            assert "display_phone_number" in result
    
    @given(credentials=whatsapp_credentials(valid=False))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_whatsapp_invalid_credentials_rejected(self, credentials):
        """
        Test that invalid WhatsApp credentials are rejected with descriptive errors
        Requirement 2.2: Validate credentials with Meta API
        """
        validator = ChannelValidator()
        
        # Test missing required fields
        phone_id = credentials.get("phone_number_id")
        token = credentials.get("access_token")
        
        if not phone_id or not token:
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_whatsapp_credentials(phone_id, token)
            assert "required" in str(exc_info.value).lower()
            return
        
        # Mock failed Meta API response
        mock_response = {
            "error": {
                "message": "Invalid OAuth access token",
                "type": "OAuthException",
                "code": 190
            }
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = create_aiohttp_mock(401, mock_response)
            
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_whatsapp_credentials(phone_id, token)
            
            # Verify descriptive error message
            assert len(str(exc_info.value)) > 0
    
    @given(credentials=instagram_credentials(valid=True))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_instagram_valid_credentials_succeed(self, credentials):
        """
        Test that valid Instagram page credentials are successfully validated
        Requirement 2.3: Validate page access token and configure webhook with Meta API
        """
        validator = ChannelValidator()
        
        # Mock successful Meta API response
        mock_response = {
            "id": credentials["page_id"],
            "name": "Test Page",
            "username": "testpage",
            "instagram_business_account": {
                "id": "987654321"
            }
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
            
            result = await validator.validate_instagram_credentials(
                credentials["page_id"],
                credentials["access_token"]
            )
            
            # Verify successful validation
            assert result["valid"] is True
            assert result["platform"] == "instagram"
            assert "page_id" in result
            assert "instagram_account_id" in result
    
    @given(credentials=instagram_credentials(valid=False))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_instagram_invalid_credentials_rejected(self, credentials):
        """
        Test that invalid Instagram credentials are rejected with descriptive errors
        Requirement 2.3: Validate page access token with Meta API
        """
        validator = ChannelValidator()
        
        # Test missing required fields
        page_id = credentials.get("page_id")
        token = credentials.get("access_token")
        
        if not page_id or not token:
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_instagram_credentials(page_id, token)
            assert "required" in str(exc_info.value).lower()
            return
        
        # Mock failed Meta API response
        mock_response = {
            "error": {
                "message": "Invalid OAuth access token",
                "type": "OAuthException",
                "code": 190
            }
        }
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.return_value = create_aiohttp_mock(401, mock_response)
            
            with pytest.raises(ChannelValidationError) as exc_info:
                await validator.validate_instagram_credentials(page_id, token)
            
            # Verify descriptive error message
            assert len(str(exc_info.value)) > 0
    
    @given(config=webchat_config(valid=True))
    @settings(max_examples=100, deadline=5000)
    def test_webchat_valid_config_succeeds(self, config):
        """
        Test that valid WebChat configuration generates unique widget_id
        Requirement 2.4: Generate unique widget_id and provide embeddable chat link
        """
        validator = ChannelValidator()
        
        result = validator.validate_webchat_config(config)
        
        # Verify successful validation
        assert result["valid"] is True
        assert result["platform"] == "webchat"
        assert "widget_id" in result
        assert len(result["widget_id"]) > 0
        
        # Verify widget_id is unique (UUID format)
        import uuid
        try:
            uuid.UUID(result["widget_id"])
            is_valid_uuid = True
        except ValueError:
            is_valid_uuid = False
        
        assert is_valid_uuid, "widget_id should be a valid UUID"
        
        # Verify all config fields are preserved
        assert result["business_name"] == config["business_name"]
        assert result["primary_color"] == config["primary_color"]
        assert result["position"] == config["position"]
        assert result["welcome_message"] == config["welcome_message"]
    
    @given(config=webchat_config(valid=False))
    @settings(max_examples=100, deadline=5000)
    def test_webchat_invalid_config_rejected(self, config):
        """
        Test that invalid WebChat configuration is rejected with descriptive errors
        Requirement 2.4: Validate WebChat configuration
        """
        validator = ChannelValidator()
        
        with pytest.raises(ChannelValidationError) as exc_info:
            validator.validate_webchat_config(config)
        
        # Verify descriptive error message
        error_msg = str(exc_info.value).lower()
        assert len(error_msg) > 0
        
        # Verify error describes the specific issue
        if not config.get("business_name"):
            assert "business_name" in error_msg or "required" in error_msg
        elif config.get("primary_color") and not config["primary_color"].startswith("#"):
            assert "color" in error_msg or "hex" in error_msg
        elif config.get("position") and config["position"] not in ["bottom-right", "bottom-left", "top-right", "top-left"]:
            assert "position" in error_msg or "invalid" in error_msg
    
    @given(
        channel_type=st.sampled_from(["telegram", "whatsapp", "instagram", "webchat"]),
        seed=st.integers(min_value=0, max_value=1000000)
    )
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_channel_validation_consistency(self, channel_type, seed):
        """
        Test that channel validation is consistent across all channel types
        All channel types should follow the same validation pattern:
        - Valid credentials return success with channel info
        - Invalid credentials raise ChannelValidationError with descriptive message
        """
        validator = ChannelValidator()
        
        # Generate valid credentials for each channel type
        if channel_type == "telegram":
            credentials = {"bot_token": f"{seed}:{'A' * 35}"}
            
            mock_response = {
                "ok": True,
                "result": {
                    "id": seed,
                    "username": f"bot_{seed}",
                    "first_name": "Test Bot"
                }
            }
            
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
                
                result = await validator.validate_channel_credentials(channel_type, credentials)
                
                assert result["valid"] is True
                assert "bot_id" in result or "bot_username" in result
        
        elif channel_type == "whatsapp":
            credentials = {
                "phone_number_id": str(seed),
                "access_token": f"token_{seed}"
            }
            
            mock_response = {
                "id": str(seed),
                "display_phone_number": "+1234567890",
                "verified_name": "Test Business"
            }
            
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
                
                result = await validator.validate_channel_credentials(channel_type, credentials)
                
                assert result["valid"] is True
                assert result["platform"] == "whatsapp"
        
        elif channel_type == "instagram":
            credentials = {
                "page_id": str(seed),
                "access_token": f"token_{seed}"
            }
            
            mock_response = {
                "id": str(seed),
                "name": "Test Page",
                "instagram_business_account": {"id": str(seed)}
            }
            
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
                
                result = await validator.validate_channel_credentials(channel_type, credentials)
                
                assert result["valid"] is True
                assert result["platform"] == "instagram"
        
        elif channel_type == "webchat":
            credentials = {
                "business_name": f"Business {seed}",
                "primary_color": "#FF5733",
                "position": "bottom-right",
                "welcome_message": f"Welcome {seed}"
            }
            
            result = await validator.validate_channel_credentials(channel_type, credentials)
            
            assert result["valid"] is True
            assert result["platform"] == "webchat"
            assert "widget_id" in result
    
    @given(channel_type=st.sampled_from(["telegram", "whatsapp", "instagram", "webchat"]))
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_unsupported_channel_type_rejected(self, channel_type):
        """
        Test that unsupported channel types are properly rejected
        """
        validator = ChannelValidator()
        
        # Test with completely invalid channel type
        with pytest.raises(ChannelValidationError) as exc_info:
            await validator.validate_channel_credentials("invalid_type", {})
        
        assert "unsupported" in str(exc_info.value).lower()
    
    @given(
        channel_type=st.sampled_from(["telegram", "whatsapp", "instagram", "webchat"]),
        seed=st.integers(min_value=0, max_value=1000)
    )
    @settings(max_examples=100, deadline=5000)
    @pytest.mark.asyncio
    async def test_convenience_function_validate_channel_connection(self, channel_type, seed):
        """
        Test the convenience function for channel validation
        Ensures the wrapper function properly handles success and error cases
        """
        # Generate valid credentials
        if channel_type == "telegram":
            credentials = {"bot_token": f"{seed}:{'A' * 35}"}
            mock_response = {"ok": True, "result": {"id": seed, "username": f"bot_{seed}"}}
            
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
                
                is_valid, result, error = await validate_channel_connection(channel_type, credentials)
                
                assert is_valid is True
                assert result is not None
                assert error is None
        
        elif channel_type == "whatsapp":
            credentials = {"phone_number_id": str(seed), "access_token": f"token_{seed}"}
            mock_response = {"id": str(seed), "display_phone_number": "+1234567890"}
            
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
                
                is_valid, result, error = await validate_channel_connection(channel_type, credentials)
                
                assert is_valid is True
                assert result is not None
                assert error is None
        
        elif channel_type == "instagram":
            credentials = {"page_id": str(seed), "access_token": f"token_{seed}"}
            mock_response = {"id": str(seed), "name": "Test", "instagram_business_account": {"id": str(seed)}}
            
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session_class.return_value = create_aiohttp_mock(200, mock_response)
                
                is_valid, result, error = await validate_channel_connection(channel_type, credentials)
                
                assert is_valid is True
                assert result is not None
                assert error is None
        
        elif channel_type == "webchat":
            credentials = {
                "business_name": f"Business {seed}",
                "primary_color": "#FF5733",
                "position": "bottom-right",
                "welcome_message": "Welcome"
            }
            
            is_valid, result, error = await validate_channel_connection(channel_type, credentials)
            
            assert is_valid is True
            assert result is not None
            assert error is None
