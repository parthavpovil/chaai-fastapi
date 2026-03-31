"""
Channel Connection Validation Service
Validates channel credentials for Telegram, WhatsApp, Instagram, and WebChat
"""
import uuid
import aiohttp
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.config import settings


class ChannelValidationError(Exception):
    """Base exception for channel validation errors"""
    pass


class ChannelValidator:
    """
    Service for validating channel connections and credentials
    Supports Telegram, WhatsApp Business, Instagram, and WebChat
    """
    
    def __init__(self):
        self.session_timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
    
    async def validate_telegram_bot(self, bot_token: str) -> Dict[str, Any]:
        """
        Validate Telegram bot token via Telegram Bot API
        
        Args:
            bot_token: Telegram bot token
        
        Returns:
            Validation result with bot information
        
        Raises:
            ChannelValidationError: If validation fails
        """
        if not bot_token or not bot_token.strip():
            raise ChannelValidationError("Bot token is required")
        
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            
            async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise ChannelValidationError("Invalid bot token or API error")
                    
                    data = await response.json()
                    
                    if not data.get("ok"):
                        error_desc = data.get("description", "Unknown error")
                        raise ChannelValidationError(f"Telegram API error: {error_desc}")
                    
                    bot_info = data.get("result", {})
                    
                    return {
                        "valid": True,
                        "bot_id": bot_info.get("id"),
                        "bot_username": bot_info.get("username"),
                        "bot_name": bot_info.get("first_name", ""),
                        "can_join_groups": bot_info.get("can_join_groups", False),
                        "can_read_all_group_messages": bot_info.get("can_read_all_group_messages", False),
                        "supports_inline_queries": bot_info.get("supports_inline_queries", False)
                    }
                    
        except aiohttp.ClientError as e:
            raise ChannelValidationError(f"Network error validating Telegram bot: {str(e)}")
        except Exception as e:
            if isinstance(e, ChannelValidationError):
                raise
            raise ChannelValidationError(f"Telegram validation failed: {str(e)}")

    async def register_telegram_webhook(self, bot_token: str) -> Dict[str, Any]:
        """
        Register Telegram webhook for the provided bot token.

        Args:
            bot_token: Telegram bot token

        Returns:
            Telegram API response payload

        Raises:
            ChannelValidationError: If webhook registration fails
        """
        if not bot_token or not bot_token.strip():
            raise ChannelValidationError("Bot token is required for webhook registration")

        app_url = settings.APP_URL.rstrip("/")
        parsed_app_url = urlparse(app_url)
        if parsed_app_url.scheme.lower() != "https":
            raise ChannelValidationError(
                "Invalid APP_URL for Telegram webhook. "
                "Set APP_URL to a public HTTPS URL (example: https://api.example.com)."
            )

        if not parsed_app_url.netloc:
            raise ChannelValidationError(
                "Invalid APP_URL for Telegram webhook. "
                "APP_URL must include a valid host, e.g. https://api.example.com"
            )

        webhook_url = f"{app_url}/webhooks/telegram/{bot_token}"
        telegram_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

        payload: Dict[str, Any] = {"url": webhook_url}
        if settings.TELEGRAM_SECRET_TOKEN:
            payload["secret_token"] = settings.TELEGRAM_SECRET_TOKEN

        try:
            async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
                async with session.post(telegram_url, json=payload) as response:
                    if response.status != 200:
                        error_body = await response.text()
                        error_detail = error_body
                        try:
                            error_json = await response.json(content_type=None)
                            if isinstance(error_json, dict):
                                error_detail = error_json.get("description") or str(error_json)
                        except Exception:
                            pass
                        raise ChannelValidationError(
                            f"Telegram setWebhook failed with HTTP {response.status}: {error_detail}"
                        )

                    data = await response.json()
                    if not data.get("ok"):
                        error_desc = data.get("description", "Unknown error")
                        raise ChannelValidationError(
                            f"Telegram setWebhook error: {error_desc}"
                        )

                    return data
        except aiohttp.ClientError as e:
            raise ChannelValidationError(
                f"Network error registering Telegram webhook: {str(e)}"
            )
        except Exception as e:
            if isinstance(e, ChannelValidationError):
                raise
            raise ChannelValidationError(
                f"Telegram webhook registration failed: {str(e)}"
            )
    
    async def validate_whatsapp_credentials(
        self, 
        phone_number_id: str, 
        access_token: str
    ) -> Dict[str, Any]:
        """
        Validate WhatsApp Business credentials via Meta Graph API
        
        Args:
            phone_number_id: WhatsApp Business phone number ID
            access_token: Meta access token
        
        Returns:
            Validation result with phone number information
        
        Raises:
            ChannelValidationError: If validation fails
        """
        if not phone_number_id or not access_token:
            raise ChannelValidationError("Phone number ID and access token are required")
        
        try:
            url = f"https://graph.facebook.com/v18.0/{phone_number_id}"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 401:
                        raise ChannelValidationError("Invalid access token")
                    elif response.status == 404:
                        raise ChannelValidationError("Phone number ID not found")
                    elif response.status != 200:
                        raise ChannelValidationError(f"Meta API error: HTTP {response.status}")
                    
                    data = await response.json()
                    
                    if "error" in data:
                        error_msg = data["error"].get("message", "Unknown error")
                        raise ChannelValidationError(f"Meta API error: {error_msg}")
                    
                    return {
                        "valid": True,
                        "phone_number_id": data.get("id"),
                        "display_phone_number": data.get("display_phone_number"),
                        "verified_name": data.get("verified_name"),
                        "quality_rating": data.get("quality_rating"),
                        "platform": "whatsapp"
                    }
                    
        except aiohttp.ClientError as e:
            raise ChannelValidationError(f"Network error validating WhatsApp: {str(e)}")
        except Exception as e:
            if isinstance(e, ChannelValidationError):
                raise
            raise ChannelValidationError(f"WhatsApp validation failed: {str(e)}")
    
    async def validate_instagram_credentials(
        self, 
        page_id: str, 
        access_token: str
    ) -> Dict[str, Any]:
        """
        Validate Instagram page credentials via Meta Graph API
        
        Args:
            page_id: Instagram page ID
            access_token: Meta access token
        
        Returns:
            Validation result with page information
        
        Raises:
            ChannelValidationError: If validation fails
        """
        if not page_id or not access_token:
            raise ChannelValidationError("Page ID and access token are required")
        
        try:
            # First, get page info
            url = f"https://graph.facebook.com/v18.0/{page_id}"
            headers = {"Authorization": f"Bearer {access_token}"}
            params = {"fields": "id,name,username,instagram_business_account"}
            
            async with aiohttp.ClientSession(timeout=self.session_timeout) as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 401:
                        raise ChannelValidationError("Invalid access token")
                    elif response.status == 404:
                        raise ChannelValidationError("Page ID not found")
                    elif response.status != 200:
                        raise ChannelValidationError(f"Meta API error: HTTP {response.status}")
                    
                    data = await response.json()
                    
                    if "error" in data:
                        error_msg = data["error"].get("message", "Unknown error")
                        raise ChannelValidationError(f"Meta API error: {error_msg}")
                    
                    # Check if page has Instagram business account
                    instagram_account = data.get("instagram_business_account")
                    if not instagram_account:
                        raise ChannelValidationError("Page does not have an Instagram business account")
                    
                    return {
                        "valid": True,
                        "page_id": data.get("id"),
                        "page_name": data.get("name"),
                        "page_username": data.get("username"),
                        "instagram_account_id": instagram_account.get("id"),
                        "platform": "instagram"
                    }
                    
        except aiohttp.ClientError as e:
            raise ChannelValidationError(f"Network error validating Instagram: {str(e)}")
        except Exception as e:
            if isinstance(e, ChannelValidationError):
                raise
            raise ChannelValidationError(f"Instagram validation failed: {str(e)}")
    
    def generate_webchat_widget_id(self) -> str:
        """
        Generate unique widget ID for WebChat channel
        
        Returns:
            Unique widget ID
        """
        return str(uuid.uuid4())
    
    def validate_webchat_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate WebChat channel configuration
        
        Args:
            config: WebChat configuration
        
        Returns:
            Validated configuration with widget ID
        
        Raises:
            ChannelValidationError: If configuration is invalid
        """
        required_fields = ["business_name", "primary_color", "position", "welcome_message"]
        
        for field in required_fields:
            if field not in config or not config[field]:
                raise ChannelValidationError(f"Missing required field: {field}")
        
        # Validate position
        valid_positions = ["bottom-right", "bottom-left", "top-right", "top-left"]
        if config["position"] not in valid_positions:
            raise ChannelValidationError(f"Invalid position. Must be one of: {valid_positions}")
        
        # Validate color format (hex color)
        color = config["primary_color"]
        if not color.startswith("#") or len(color) != 7:
            raise ChannelValidationError("Primary color must be a valid hex color (e.g., #FF5733)")
        
        # Generate widget ID
        widget_id = self.generate_webchat_widget_id()
        
        return {
            "valid": True,
            "widget_id": widget_id,
            "business_name": config["business_name"],
            "primary_color": config["primary_color"],
            "position": config["position"],
            "welcome_message": config["welcome_message"],
            "platform": "webchat"
        }
    
    async def validate_channel_credentials(
        self,
        channel_type: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate channel credentials based on channel type
        
        Args:
            channel_type: Type of channel ("telegram", "whatsapp", "instagram", "webchat")
            credentials: Channel credentials
        
        Returns:
            Validation result with channel information
        
        Raises:
            ChannelValidationError: If validation fails
        """
        if channel_type == "telegram":
            bot_token = credentials.get("bot_token")
            return await self.validate_telegram_bot(bot_token)
        
        elif channel_type == "whatsapp":
            phone_number_id = credentials.get("phone_number_id")
            access_token = credentials.get("access_token")
            return await self.validate_whatsapp_credentials(phone_number_id, access_token)
        
        elif channel_type == "instagram":
            page_id = credentials.get("page_id")
            access_token = credentials.get("access_token")
            return await self.validate_instagram_credentials(page_id, access_token)
        
        elif channel_type == "webchat":
            return self.validate_webchat_config(credentials)
        
        else:
            raise ChannelValidationError(f"Unsupported channel type: {channel_type}")


# ─── Convenience Functions ────────────────────────────────────────────────────

async def validate_channel_connection(
    channel_type: str,
    credentials: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Convenience function to validate channel connection
    
    Args:
        channel_type: Channel type
        credentials: Channel credentials
    
    Returns:
        Tuple of (is_valid, validation_result, error_message)
    """
    validator = ChannelValidator()
    
    try:
        result = await validator.validate_channel_credentials(channel_type, credentials)
        return True, result, None
    except ChannelValidationError as e:
        return False, {}, str(e)
    except Exception as e:
        return False, {}, f"Validation error: {str(e)}"


def generate_webchat_widget() -> str:
    """
    Generate unique WebChat widget ID
    
    Returns:
        Unique widget ID
    """
    validator = ChannelValidator()
    return validator.generate_webchat_widget_id()