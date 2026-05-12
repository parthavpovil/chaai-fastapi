"""
Webhook Handlers for All Channel Types
Handles incoming webhooks from Telegram, WhatsApp, Instagram with signature verification
"""
import json
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.channel import Channel
from app.services.webhook_security import verify_webhook_signature, WebhookSecurityError
from app.services.encryption import decrypt_credential


class WebhookProcessingError(Exception):
    """Webhook processing error with an HTTP status hint for the router.

    status_code semantics:
      400 — bad request (auth failure, malformed payload); provider should NOT
            keep retrying with the same payload.
      200 — permanent no-op (channel not found / inactive); return 200 so the
            provider stops retrying (retries can never succeed).
      500 — transient error; provider should retry.
    """
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


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
            # For WebChat, identifier is widget_id stored inside config JSONB
            result = await self.db.execute(
                select(Channel)
                .where(Channel.type == "webchat")
                .where(Channel.config["widget_id"].astext == identifier)
                .where(Channel.is_active == True)
            )
        else:
            # For other channels, we'll need to match against encrypted config
            # This is a simplified approach - in production, you might want
            # to store a hash of the identifier for faster lookups
            result = await self.db.execute(
                select(Channel)
                .where(Channel.type == channel_type)
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
        if not channel.config:
            return False

        try:
            if channel.type == "telegram":
                # For Telegram, identifier is bot token
                encrypted_token = channel.config.get("bot_token")
                if encrypted_token:
                    decrypted_token = decrypt_credential(encrypted_token)
                    return decrypted_token == identifier

            elif channel.type in ["whatsapp", "instagram"]:
                # For Meta platforms, identifier could be phone_number_id or page_id
                for key in ["phone_number_id", "page_id"]:
                    encrypted_id = channel.config.get(key)
                    if encrypted_id:
                        decrypted_id = decrypt_credential(encrypted_id)
                        if decrypted_id == identifier:
                            return True

            elif channel.type == "whatsapp_unofficial":
                encrypted_tenant_id = channel.config.get("tenant_id")
                if encrypted_tenant_id:
                    return decrypt_credential(encrypted_tenant_id) == identifier

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
            # Enforce secret token when TELEGRAM_SECRET_TOKEN is configured.
            # Rejecting absent headers closes the bypass where forged requests
            # omit the header entirely and skip all verification.
            secret_token = headers.get("X-Telegram-Bot-Api-Secret-Token")
            if settings.TELEGRAM_SECRET_TOKEN:
                if not secret_token:
                    raise WebhookProcessingError("Missing X-Telegram-Bot-Api-Secret-Token header")
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
                raise WebhookProcessingError("Channel not found or inactive", status_code=200)
            
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
            raise WebhookProcessingError(f"Telegram webhook processing failed: {str(e)}", status_code=500)
    
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
            # Enforce HMAC signature when WHATSAPP_APP_SECRET is configured.
            signature = headers.get("X-Hub-Signature-256")
            if settings.WHATSAPP_APP_SECRET:
                if not signature:
                    raise WebhookProcessingError("Missing X-Hub-Signature-256 header")
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

            # Check for delivery status updates first
            statuses = self._extract_whatsapp_statuses(webhook_data)
            if statuses:
                channel = await self.get_channel_by_webhook_path("whatsapp", phone_number_id)
                if not channel:
                    raise WebhookProcessingError("Channel not found or inactive", status_code=200)
                return {
                    "status": "status_update",
                    "channel_id": channel.id,
                    "workspace_id": channel.workspace_id,
                    "statuses": statuses,
                    "platform": "whatsapp"
                }

            # Extract message data
            message_data = self._extract_whatsapp_message(webhook_data, phone_number_id)
            if not message_data:
                return {"status": "ignored", "reason": "No processable message"}

            # Get channel
            channel = await self.get_channel_by_webhook_path("whatsapp", phone_number_id)
            if not channel:
                raise WebhookProcessingError("Channel not found or inactive", status_code=200)

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
            raise WebhookProcessingError(f"WhatsApp webhook processing failed: {str(e)}", status_code=500)
    
    def _extract_whatsapp_message(
        self,
        webhook_data: Dict[str, Any],
        phone_number_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extract message data from WhatsApp webhook — handles all message types.

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
                    msg_id = message.get("id")
                    from_number = message.get("from")

                    base = {
                        "external_contact_id": from_number,
                        "contact_name": f"WhatsApp User {(from_number or '')[-4:]}",
                        "contact_data": {"phone_number": from_number},
                        "message_metadata": {
                            "timestamp": message.get("timestamp"),
                            "phone_number_id": phone_number_id,
                            "platform": "whatsapp"
                        }
                    }

                    if message_type == "text":
                        content = message.get("text", {}).get("body", "")
                        if not content.strip():
                            continue
                        return {
                            **base,
                            "external_message_id": msg_id,
                            "content": content,
                            "msg_type": "text",
                        }

                    elif message_type in ("image", "video", "audio", "document", "sticker"):
                        media_obj = message.get(message_type, {})
                        return {
                            **base,
                            "external_message_id": msg_id,
                            "content": media_obj.get("caption", ""),
                            "msg_type": message_type,
                            "media_id": media_obj.get("id"),
                            "media_mime_type": media_obj.get("mime_type"),
                            "media_filename": media_obj.get("filename"),
                        }

                    elif message_type == "location":
                        loc = message.get("location", {})
                        return {
                            **base,
                            "external_message_id": msg_id,
                            "content": loc.get("name", "Location shared"),
                            "msg_type": "location",
                            "location_lat": loc.get("latitude"),
                            "location_lng": loc.get("longitude"),
                            "location_name": loc.get("name"),
                        }

                    elif message_type == "interactive":
                        interactive = message.get("interactive", {})
                        interactive_type = interactive.get("type")
                        if interactive_type == "button_reply":
                            btn = interactive.get("button_reply", {})
                            return {
                                **base,
                                "external_message_id": msg_id,
                                "content": btn.get("title", ""),
                                "msg_type": "interactive",
                                "interactive_id": btn.get("id"),
                            }
                        elif interactive_type == "list_reply":
                            row = interactive.get("list_reply", {})
                            return {
                                **base,
                                "external_message_id": msg_id,
                                "content": row.get("title", ""),
                                "msg_type": "interactive",
                                "interactive_id": row.get("id"),
                            }

                    elif message_type == "reaction":
                        reaction = message.get("reaction", {})
                        return {
                            **base,
                            "external_message_id": msg_id,
                            "content": reaction.get("emoji", ""),
                            "msg_type": "reaction",
                        }

        return None

    def _extract_whatsapp_statuses(
        self,
        webhook_data: Dict[str, Any]
    ) -> list:
        """
        Extract delivery status updates from WhatsApp webhook.

        Args:
            webhook_data: WhatsApp webhook payload

        Returns:
            List of status dicts
        """
        statuses = []
        for entry in webhook_data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                for status in change.get("value", {}).get("statuses", []):
                    statuses.append({
                        "whatsapp_msg_id": status.get("id"),
                        "status": status.get("status"),
                        "timestamp": status.get("timestamp"),
                        "recipient_id": status.get("recipient_id"),
                        "error": status.get("errors", [{}])[0].get("title") if status.get("errors") else None
                    })
        return statuses
    
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
            # Enforce HMAC signature when INSTAGRAM_APP_SECRET is configured.
            signature = headers.get("X-Hub-Signature-256")
            if settings.INSTAGRAM_APP_SECRET:
                if not signature:
                    raise WebhookProcessingError("Missing X-Hub-Signature-256 header")
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
                raise WebhookProcessingError("Channel not found or inactive", status_code=200)
            
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
            raise WebhookProcessingError(f"Instagram webhook processing failed: {str(e)}", status_code=500)
    
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
    
    async def handle_whatsapp_unofficial_webhook(
        self,
        payload: bytes,
        headers: Dict[str, str],
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        Handle inbound webhook from Baileys gateway.

        Args:
            payload: Raw JSON body
            headers: Request headers (must contain X-Webhook-Secret)
            tenant_id: Tenant ID used to look up the channel

        Returns:
            Processed webhook data

        Raises:
            WebhookProcessingError: If processing fails
        """
        try:
            try:
                webhook_data = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise WebhookProcessingError(f"Invalid JSON payload: {str(e)}")

            channel = await self.get_channel_by_webhook_path("whatsapp_unofficial", tenant_id)
            if not channel:
                raise WebhookProcessingError("Channel not found or inactive", status_code=200)

            # Verify X-Webhook-Secret against the global WHATSAPP_WEBHOOK_SECRET setting
            import hmac as _hmac
            provided_secret = headers.get("x-webhook-secret") or headers.get("X-Webhook-Secret", "")
            if settings.WHATSAPP_WEBHOOK_SECRET:
                if not _hmac.compare_digest(provided_secret, settings.WHATSAPP_WEBHOOK_SECRET):
                    raise WebhookProcessingError("Invalid webhook secret")

            event = webhook_data.get("event")

            # Session lifecycle events — acknowledge and ignore
            if event in ("qr", "connected", "disconnected"):
                return {"status": "ignored", "reason": f"session event: {event}"}

            if event != "message":
                return {"status": "ignored", "reason": f"unknown event: {event}"}

            message_data = self._extract_unofficial_whatsapp_message(webhook_data, tenant_id)
            if not message_data:
                return {"status": "ignored", "reason": "No processable message"}

            return {
                "status": "success",
                "channel_id": channel.id,
                "workspace_id": channel.workspace_id,
                "message_data": message_data,
                "platform": "whatsapp_unofficial",
            }

        except WebhookProcessingError:
            raise
        except Exception as e:
            raise WebhookProcessingError(
                f"Unofficial WhatsApp webhook processing failed: {str(e)}", status_code=500
            )

    def _extract_unofficial_whatsapp_message(
        self,
        webhook_data: Dict[str, Any],
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract message data from Baileys gateway webhook payload.
        """
        data = webhook_data.get("data", {})
        sender_jid = data.get("senderId", "")
        phone = sender_jid.split("@")[0]  # strip @s.whatsapp.net or @g.us
        if not phone:
            return None

        msg_type = data.get("type", "text")
        timestamp_ms = data.get("timestamp") or 0

        base = {
            "external_contact_id": phone,
            "external_message_id": data.get("messageId"),
            "contact_name": f"WhatsApp User {phone[-4:]}",
            "contact_data": {"phone_number": phone},
            "message_metadata": {
                "timestamp": timestamp_ms // 1000,  # ms → s
                "tenant_id": tenant_id,
                "platform": "whatsapp_unofficial",
                "chat_id": data.get("chatId"),
            },
        }

        if msg_type == "text":
            content = data.get("text", "")
            if not content.strip():
                return None
            return {**base, "content": content, "msg_type": "text"}

        elif msg_type in ("image", "video", "audio", "document"):
            return {
                **base,
                "content": data.get("caption", ""),
                "msg_type": msg_type,
                "media_mime_type": data.get("mimeType"),
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
    elif channel_type == "whatsapp_unofficial":
        return await handlers.handle_whatsapp_unofficial_webhook(payload, headers, identifier)
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