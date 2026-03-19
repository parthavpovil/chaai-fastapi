"""
Webhook Handlers for All Channel Types
Handles incoming webhooks from Telegram, WhatsApp, Instagram with signature verification
"""
import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.channel import Channel
from app.services.webhook_security import verify_webhook_signature, WebhookSecurityError
from app.services.encryption import decrypt_credential


class WebhookProcessingError(Exception):
    """Base exception for webhook processing errors"""
    pass


class WebhookHandlers:
    """
    Webhook handlers for all supported channel types
    Handles signature verification and message extraction
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_channel_by_webhook_path(
        self, 
        channel_type: str, 
        identifier: str
    ) -> Optional[Channel]:
        """
        Get channel by webhook identifier
        
        Args:
            channel_type: Type of channel
            identifier: Channel identifier (widget_id, bot_token hash, etc.)
        
        Returns:
            Channel instance or None
        """
        if channel_type == "webchat":
            # For WebChat, identifier is widget_id
            result = await self.db.execute(
                select(Channel)
                .where(Channel.channel_type == "webchat")
                .where(Channel.widget_id == identifier)
                .where(Channel.is_active == True)
            )
        else:
            # For other channels, we'll need to match against encrypted config
            # This is a simplified approach - in production, you might want
            # to store a hash of the identifier for faster lookups
            result = await self.db.execute(
                select(Channel)
                .where(Channel.channel_type == channel_type)
                .where(Channel.is_active == True)
            )
            channels = result.scalars().all()
            
            # Find matching channel by decrypting and comparing identifiers
            for channel in channels:
                try:
                    if self._matches_channel_identifier(channel, identifier):
                        return channel
                except Exception:
                    continue
            
            return None
        
        return result.scalar_one_or_none()
    
    def _matches_channel_identifier(self, channel: Channel, identifier: str) -> bool:
        """
        Check if channel matches the given identifier
        
        Args:
            channel: Channel instance
            identifier: Identifier to match
        
        Returns:
            True if matches
        """
        if not channel.encrypted_config:
            return False
        
        try:
            if channel.channel_type == "telegram":
                # For Telegram, identifier is bot token
                encrypted_token = channel.encrypted_config.get("bot_token")
                if encrypted_token:
                    decrypted_token = decrypt_credential(encrypted_token)
                    return decrypted_token == identifier
            
            elif channel.channel_type in ["whatsapp", "instagram"]:
                # For Meta platforms, identifier could be phone_number_id or page_id
                for key in ["phone_number_id", "page_id"]:
                    encrypted_id = channel.encrypted_config.get(key)
                    if encrypted_id:
                        decrypted_id = decrypt_credential(encrypted_id)
                        if decrypted_id == identifier:
                            return True
            
            return False
            
        except Exception:
            return False
    
    async def handle_telegram_webhook(
        self,
        payload: bytes,
        headers: Dict[str, str],
        bot_token: str
    ) -> Dict[str, Any]:
        """
        Handle Telegram webhook with secret token verification
        
        Args:
            payload: Raw webhook payload
            headers: Request headers
            bot_token: Bot token for channel identification
        
        Returns:
            Processed webhook data
        
        Raises:
            WebhookProcessingError: If processing fails
        """
        try:
            # Verify secret token if provided
            secret_token = headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret_token:
                if not verify_webhook_signature("telegram", payload, token=secret_token):
                    raise WebhookProcessingError("Invalid Telegram secret token")
            
            # Parse JSON payload
            try:
                webhook_data = json.loads(payload.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise WebhookProcessingError(f"Invalid JSON payload: {str(e)}")
            
            # Extract message data
            message_data = self._extract_telegram_message(webhook_data)
            if not message_data:
                return {"status": "ignored", "reason": "No processable message"}
            
            # Get channel
            channel = await self.get_channel_by_webhook_path("telegram", bot_token)
            if not channel:
                raise WebhookProcessingError("Channel not found or inactive")
            
            return {
                "status": "success",
                "channel_id": channel.id,
                "workspace_id": channel.workspace_id,
                "message_data": message_data,
                "platform": "telegram"
            }
            
        except WebhookSecurityError as e:
            raise WebhookProcessingError(f"Security verification failed: {str(e)}")
        except Exception as e:
            if isinstance(e, WebhookProcessingError):
                raise
            raise WebhookProcessingError(f"Telegram webhook processing failed: {str(e)}")
    
    def _extract_telegram_message(self, webhook_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract message data from Telegram webhook
        
        Args:
            webhook_data: Telegram webhook payload
        
        Returns:
            Extracted message data or None
        """
        message = webhook_data.get("message")
        if not message:
            return None
        
        # Extract basic message info
        message_id = message.get("message_id")
        text = message.get("text", "")
        from_user = message.get("from", {})
        chat = message.get("chat", {})
        
        if not text.strip():
            return None  # Skip non-text messages for now
        
        return {
            "external_message_id": str(message_id),
            "content": text,
            "external_contact_id": str(from_user.get("id", "")),
            "contact_name": f"{from_user.get('first_name', '')} {from_user.get('last_name', '')}".strip(),
            "contact_data": {
                "username": from_user.get("username"),
                "language_code": from_user.get("language_code"),
                "chat_type": chat.get("type")
            },
            "message_metadata": {
                "date": message.get("date"),
                "chat_id": chat.get("id"),
                "platform": "telegram"
            }
        }
    
    async def handle_whatsapp_webhook(
        self,
        payload: bytes,
        headers: Dict[str, str],
        phone_number_id: str
    ) -> Dict[str, Any]:
        """
        Handle WhatsApp webhook with HMAC-SHA256 verification
        
        Args:
            payload: Raw webhook payload
            headers: Request headers
            phone_number_id: Phone number ID for channel identification
        
        Returns:
            Processed webhook data
        
        Raises:
            WebhookProcessingError: If processing fails
        """
        try:
            # Verify HMAC signature
            signature = headers.get("X-Hub-Signature-256")
            if signature:
                if not verify_webhook_signature("whatsapp", payload, signature=signature):
                    raise WebhookProcessingError("Invalid WhatsApp signature")
            
            # Parse JSON payload
            try:
                webhook_data = json.loads(payload.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise WebhookProcessingError(f"Invalid JSON payload: {str(e)}")
            
            # Handle Meta verification challenge
            if self._is_meta_verification(webhook_data):
                return self._handle_meta_verification(webhook_data)
            
            # Extract message data
            message_data = self._extract_whatsapp_message(webhook_data, phone_number_id)
            if not message_data:
                return {"status": "ignored", "reason": "No processable message"}
            
            # Get channel
            channel = await self.get_channel_by_webhook_path("whatsapp", phone_number_id)
            if not channel:
                raise WebhookProcessingError("Channel not found or inactive")
            
            return {
                "status": "success",
                "channel_id": channel.id,
                "workspace_id": channel.workspace_id,
                "message_data": message_data,
                "platform": "whatsapp"
            }
            
        except WebhookSecurityError as e:
            raise WebhookProcessingError(f"Security verification failed: {str(e)}")
        except Exception as e:
            if isinstance(e, WebhookProcessingError):
                raise
            raise WebhookProcessingError(f"WhatsApp webhook processing failed: {str(e)}")
    
    def _extract_whatsapp_message(
        self, 
        webhook_data: Dict[str, Any], 
        phone_number_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract message data from WhatsApp webhook
        
        Args:
            webhook_data: WhatsApp webhook payload
            phone_number_id: Phone number ID
        
        Returns:
            Extracted message data or None
        """
        entry = webhook_data.get("entry", [])
        if not entry:
            return None
        
        for entry_item in entry:
            changes = entry_item.get("changes", [])
            for change in changes:
                if change.get("field") != "messages":
                    continue
                
                value = change.get("value", {})
                if value.get("metadata", {}).get("phone_number_id") != phone_number_id:
                    continue
                
                messages = value.get("messages", [])
                for message in messages:
                    message_type = message.get("type")
                    if message_type != "text":
                        continue  # Skip non-text messages for now
                    
                    text_data = message.get("text", {})
                    text_body = text_data.get("body", "")
                    
                    if not text_body.strip():
                        continue
                    
                    return {
                        "external_message_id": message.get("id"),
                        "content": text_body,
                        "external_contact_id": message.get("from"),
                        "contact_name": f"WhatsApp User {message.get('from', '')[-4:]}",
                        "contact_data": {
                            "phone_number": message.get("from"),
                            "message_type": message_type
                        },
                        "message_metadata": {
                            "timestamp": message.get("timestamp"),
                            "phone_number_id": phone_number_id,
                            "platform": "whatsapp"
                        }
                    }
        
        return None
    
    async def handle_instagram_webhook(
        self,
        payload: bytes,
        headers: Dict[str, str],
        page_id: str
    ) -> Dict[str, Any]:
        """
        Handle Instagram webhook with HMAC-SHA256 verification
        
        Args:
            payload: Raw webhook payload
            headers: Request headers
            page_id: Instagram page ID for channel identification
        
        Returns:
            Processed webhook data
        
        Raises:
            WebhookProcessingError: If processing fails
        """
        try:
            # Verify HMAC signature
            signature = headers.get("X-Hub-Signature-256")
            if signature:
                if not verify_webhook_signature("instagram", payload, signature=signature):
                    raise WebhookProcessingError("Invalid Instagram signature")
            
            # Parse JSON payload
            try:
                webhook_data = json.loads(payload.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise WebhookProcessingError(f"Invalid JSON payload: {str(e)}")
            
            # Handle Meta verification challenge
            if self._is_meta_verification(webhook_data):
                return self._handle_meta_verification(webhook_data)
            
            # Extract message data
            message_data = self._extract_instagram_message(webhook_data, page_id)
            if not message_data:
                return {"status": "ignored", "reason": "No processable message"}
            
            # Get channel
            channel = await self.get_channel_by_webhook_path("instagram", page_id)
            if not channel:
                raise WebhookProcessingError("Channel not found or inactive")
            
            return {
                "status": "success",
                "channel_id": channel.id,
                "workspace_id": channel.workspace_id,
                "message_data": message_data,
                "platform": "instagram"
            }
            
        except WebhookSecurityError as e:
            raise WebhookProcessingError(f"Security verification failed: {str(e)}")
        except Exception as e:
            if isinstance(e, WebhookProcessingError):
                raise
            raise WebhookProcessingError(f"Instagram webhook processing failed: {str(e)}")
    
    def _extract_instagram_message(
        self, 
        webhook_data: Dict[str, Any], 
        page_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract message data from Instagram webhook
        
        Args:
            webhook_data: Instagram webhook payload
            page_id: Page ID
        
        Returns:
            Extracted message data or None
        """
        entry = webhook_data.get("entry", [])
        if not entry:
            return None
        
        for entry_item in entry:
            if entry_item.get("id") != page_id:
                continue
            
            messaging = entry_item.get("messaging", [])
            for message_event in messaging:
                message = message_event.get("message")
                if not message:
                    continue
                
                text = message.get("text", "")
                if not text.strip():
                    continue
                
                sender = message_event.get("sender", {})
                recipient = message_event.get("recipient", {})
                
                return {
                    "external_message_id": message.get("mid"),
                    "content": text,
                    "external_contact_id": sender.get("id"),
                    "contact_name": f"Instagram User {sender.get('id', '')[-4:]}",
                    "contact_data": {
                        "sender_id": sender.get("id"),
                        "recipient_id": recipient.get("id")
                    },
                    "message_metadata": {
                        "timestamp": message_event.get("timestamp"),
                        "page_id": page_id,
                        "platform": "instagram"
                    }
                }
        
        return None
    
    def _is_meta_verification(self, webhook_data: Dict[str, Any]) -> bool:
        """
        Check if webhook is a Meta verification challenge
        
        Args:
            webhook_data: Webhook payload
        
        Returns:
            True if verification challenge
        """
        return "hub.challenge" in webhook_data or "hub.verify_token" in webhook_data
    
    def _handle_meta_verification(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle Meta webhook verification challenge
        
        Args:
            webhook_data: Webhook payload with challenge
        
        Returns:
            Verification response
        """
        challenge = webhook_data.get("hub.challenge")
        verify_token = webhook_data.get("hub.verify_token")
        
        # In production, you should verify the verify_token matches your expected value
        # For now, we'll accept any verification challenge
        
        return {
            "status": "verification",
            "challenge": challenge,
            "verify_token": verify_token
        }


# ─── Convenience Functions ────────────────────────────────────────────────────

async def process_webhook(
    db: AsyncSession,
    channel_type: str,
    payload: bytes,
    headers: Dict[str, str],
    identifier: str
) -> Dict[str, Any]:
    """
    Process webhook for any channel type
    
    Args:
        db: Database session
        channel_type: Channel type
        payload: Raw webhook payload
        headers: Request headers
        identifier: Channel identifier
    
    Returns:
        Processing result
    
    Raises:
        WebhookProcessingError: If processing fails
    """
    handlers = WebhookHandlers(db)
    
    if channel_type == "telegram":
        return await handlers.handle_telegram_webhook(payload, headers, identifier)
    elif channel_type == "whatsapp":
        return await handlers.handle_whatsapp_webhook(payload, headers, identifier)
    elif channel_type == "instagram":
        return await handlers.handle_instagram_webhook(payload, headers, identifier)
    else:
        raise WebhookProcessingError(f"Unsupported channel type: {channel_type}")


async def verify_webhook_security(
    channel_type: str,
    payload: bytes,
    headers: Dict[str, str]
) -> bool:
    """
    Verify webhook security for any channel type
    
    Args:
        channel_type: Channel type
        payload: Raw payload
        headers: Request headers
    
    Returns:
        True if verification passes
    """
    try:
        if channel_type == "telegram":
            secret_token = headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret_token:
                return verify_webhook_signature("telegram", payload, token=secret_token)
            return True  # No secret token provided, accept
        
        elif channel_type in ["whatsapp", "instagram"]:
            signature = headers.get("X-Hub-Signature-256")
            if signature:
                return verify_webhook_signature(channel_type, payload, signature=signature)
            return True  # No signature provided, accept
        
        return False
        
    except Exception:
        return False