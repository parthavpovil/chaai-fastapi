"""
Message Processing Core System
Handles message deduplication, maintenance mode checking, and processing pipeline
"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.platform_setting import PlatformSetting
from app.services.tier_manager import TierManager, TierLimitError
from app.services.usage_tracker import UsageTracker


class MessageProcessingError(Exception):
    """Base exception for message processing errors"""
    pass


class MaintenanceModeError(MessageProcessingError):
    """Raised when system is in maintenance mode"""
    pass


class DuplicateMessageError(MessageProcessingError):
    """Raised when a duplicate message is detected"""
    pass


class BlockedContactError(MessageProcessingError):
    """Raised when a message is received from a blocked contact"""
    pass


class OutsideBusinessHoursError(MessageProcessingError):
    """Raised when a message arrives outside configured business hours (inform_and_pause)"""
    def __init__(self, outside_hours_message: str):
        super().__init__(outside_hours_message)
        self.outside_hours_message = outside_hours_message


class MessageProcessor:
    """
    Core message processing service
    Handles maintenance mode checking, deduplication, and processing pipeline
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.tier_manager = TierManager(db)
        self.usage_tracker = UsageTracker(db)

    async def is_maintenance_mode(self) -> Tuple[bool, Optional[str]]:
        """
        Check if system is in maintenance mode

        Returns:
            Tuple of (is_maintenance, maintenance_message)
        """
        result = await self.db.execute(
            select(PlatformSetting.value)
            .where(PlatformSetting.key == "maintenance_mode")
        )
        maintenance_setting = result.scalar_one_or_none()

        if maintenance_setting == "true":
            # Get maintenance message
            message_result = await self.db.execute(
                select(PlatformSetting.value)
                .where(PlatformSetting.key == "maintenance_message")
            )
            maintenance_message = message_result.scalar_one_or_none()
            return True, maintenance_message or "System is currently under maintenance. Please try again later."

        return False, None

    async def check_message_duplicate(
        self,
        workspace_id: str,
        external_message_id: Optional[str],
        conversation_id: Optional[str] = None
    ) -> bool:
        """
        Check if message is a duplicate based on external_message_id

        Args:
            workspace_id: Workspace ID for isolation
            external_message_id: External message ID from platform (Telegram, WhatsApp, etc.)
            conversation_id: Optional conversation ID for additional filtering

        Returns:
            True if message is duplicate, False if unique
        """
        if not external_message_id:
            # WebChat messages don't have external IDs, so they can't be duplicates
            return False

        query = select(Message.id).where(
            Message.external_message_id == external_message_id
        )

        # Add workspace isolation by joining with conversation
        query = query.join(Conversation).where(
            Conversation.workspace_id == workspace_id
        )

        # Optionally filter by conversation
        if conversation_id:
            query = query.where(Message.conversation_id == conversation_id)

        result = await self.db.execute(query)
        existing_message = result.scalar_one_or_none()

        return existing_message is not None

    async def validate_processing_limits(self, workspace_id: str) -> bool:
        """
        Validate that workspace can process additional messages
        Checks tier limits and token usage

        Args:
            workspace_id: Workspace ID

        Returns:
            True if processing is allowed

        Raises:
            TierLimitError: If monthly message limit exceeded
        """
        # Check monthly message limit
        await self.tier_manager.check_monthly_message_limit(workspace_id, 1)
        return True

    async def get_or_create_contact(
        self,
        workspace_id: str,
        channel_id: str,
        external_contact_id: str,
        contact_name: Optional[str] = None,
        contact_data: Optional[Dict[str, Any]] = None,
        channel_type: Optional[str] = None,
    ) -> Contact:
        """
        Get existing contact or create new one

        Args:
            workspace_id: Workspace ID
            channel_id: Channel ID
            external_contact_id: External contact ID from platform
            contact_name: Display name for contact
            contact_data: Additional contact metadata
            channel_type: Channel type for source tagging (telegram, whatsapp, etc.)

        Returns:
            Contact instance
        """
        # Try to find existing contact
        result = await self.db.execute(
            select(Contact)
            .where(Contact.workspace_id == workspace_id)
            .where(Contact.channel_id == channel_id)
            .where(Contact.external_id == external_contact_id)
        )
        contact = result.scalar_one_or_none()

        if contact:
            # Update identity fields if caller provided richer data (identify() calls)
            updated = False
            if contact_data:
                if contact_data.get("email") and not contact.email:
                    contact.email = contact_data["email"]
                    updated = True
                if contact_data.get("phone") and not contact.phone:
                    contact.phone = contact_data["phone"]
                    updated = True
                if contact_data.get("metadata") and not contact.metadata:
                    contact.metadata = contact_data["metadata"]
                    updated = True
            if contact_name and not contact.name:
                contact.name = contact_name
                updated = True
            if updated:
                await self.db.commit()
                await self.db.refresh(contact)
            return contact

        # Extract structured fields from contact_data
        email = (contact_data or {}).pop("email", None) if contact_data else None
        phone = (contact_data or {}).pop("phone", None) if contact_data else None
        metadata = (contact_data or {}).pop("metadata", None) if contact_data else None

        # Create new contact
        contact = Contact(
            workspace_id=workspace_id,
            channel_id=channel_id,
            external_id=external_contact_id,
            name=contact_name or f"Contact {external_contact_id}",
            source=channel_type,
            email=email,
            phone=phone,
            metadata=metadata or contact_data or {}
        )

        self.db.add(contact)
        await self.db.commit()
        await self.db.refresh(contact)

        return contact

    async def get_or_create_conversation(
        self,
        workspace_id: str,
        contact_id: str,
        channel_id: str,
        channel_type: str = "unknown",
    ) -> Conversation:
        """
        Get existing conversation or create new one

        Args:
            workspace_id: Workspace ID
            contact_id: Contact ID
            channel_id: Channel ID
            channel_type: Channel type string

        Returns:
            Conversation instance
        """
        # Try to find existing active conversation
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.workspace_id == workspace_id)
            .where(Conversation.contact_id == contact_id)
            .where(Conversation.channel_id == channel_id)
            .where(Conversation.status.in_(["active", "escalated", "agent"]))
            .order_by(Conversation.updated_at.desc())
        )
        conversation = result.scalar_one_or_none()

        if conversation:
            return conversation

        # Create new conversation
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact_id,
            channel_id=channel_id,
            channel_type=channel_type,
            status="active"
        )

        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)

        # Fire outbound webhook for new conversation (fire-and-forget)
        try:
            import asyncio
            from app.services.outbound_webhook_service import trigger_event
            asyncio.create_task(trigger_event(
                db=self.db,
                workspace_id=str(workspace_id),
                event_type="conversation.created",
                payload={
                    "workspace_id": str(workspace_id),
                    "conversation_id": str(conversation.id),
                    "contact_id": str(contact_id),
                    "channel_id": str(channel_id),
                }
            ))
        except Exception:
            pass

        return conversation

    async def create_message(
        self,
        conversation_id: str,
        content: Optional[str] = None,
        role: str = "customer",
        channel_type: str = "webchat",
        external_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        msg_type: str = "text",
        media_url: Optional[str] = None,
        media_mime_type: Optional[str] = None,
        media_filename: Optional[str] = None,
        media_size: Optional[int] = None,
        location_lat: Optional[float] = None,
        location_lng: Optional[float] = None,
        location_name: Optional[str] = None,
        whatsapp_msg_id: Optional[str] = None,
        delivery_status: Optional[str] = None,
    ) -> Message:
        """
        Create a new message in the conversation

        Args:
            conversation_id: Conversation ID
            content: Message content (may be None for pure media messages)
            role: Role of message sender ("customer", "assistant", "agent")
            channel_type: Type of channel
            external_message_id: External message ID from platform
            metadata: Additional message metadata
            msg_type: Message type (text|image|video|audio|document|location|sticker|reaction|interactive)
            media_url: Permanent URL after storage
            media_mime_type: MIME type of media
            media_filename: Original filename (docs only)
            media_size: File size in bytes
            location_lat: Latitude for location messages
            location_lng: Longitude for location messages
            location_name: Location name/label
            whatsapp_msg_id: WhatsApp message ID (wamid) for delivery tracking
            delivery_status: Initial delivery status (sent|delivered|read|failed)

        Returns:
            Created Message instance
        """
        message = Message(
            conversation_id=conversation_id,
            content=content,
            role=role,
            channel_type=channel_type,
            external_message_id=external_message_id,
            extra_data=metadata or {},
            msg_type=msg_type,
            media_url=media_url,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
            media_size=media_size,
            location_lat=location_lat,
            location_lng=location_lng,
            location_name=location_name,
            whatsapp_msg_id=whatsapp_msg_id,
            delivery_status=delivery_status,
        )

        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)

        return message

    async def update_message_delivery_status(
        self,
        whatsapp_msg_id: str,
        status: str,
        timestamp: str,
        workspace_id: str,
        error: Optional[str] = None
    ) -> Optional[Message]:
        """
        Find message by whatsapp_message_id and update delivery fields.
        Only updates forward (sent → delivered → read, never backwards).
        """
        from datetime import timezone as tz

        STATUS_ORDER = {"sent": 1, "delivered": 2, "read": 3, "failed": 0}

        result = await self.db.execute(
            select(Message)
            .join(Conversation)
            .where(Message.whatsapp_msg_id == whatsapp_msg_id)
            .where(Conversation.workspace_id == workspace_id)
        )
        message = result.scalar_one_or_none()
        if not message:
            return None

        current_order = STATUS_ORDER.get(message.delivery_status or "sent", 1)
        new_order = STATUS_ORDER.get(status, 0)
        if new_order <= current_order and status != "failed":
            return message  # don't go backwards

        ts = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        message.delivery_status = status
        if status == "delivered":
            message.delivered_at = ts
        elif status == "read":
            message.read_at = ts
        elif status == "failed":
            message.failed_reason = error

        await self.db.commit()
        return message

    async def preprocess_message(
        self,
        workspace_id: str,
        channel_id: str,
        external_contact_id: str,
        content: Optional[str] = None,
        external_message_id: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_data: Optional[Dict[str, Any]] = None,
        message_metadata: Optional[Dict[str, Any]] = None,
        channel_type: Optional[str] = None,
        msg_type: str = "text",
        media_id: Optional[str] = None,
        media_mime_type: Optional[str] = None,
        media_filename: Optional[str] = None,
        location_lat: Optional[float] = None,
        location_lng: Optional[float] = None,
        location_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Preprocess incoming message through the complete pipeline

        Args:
            workspace_id: Workspace ID
            channel_id: Channel ID
            external_contact_id: External contact ID from platform
            content: Message content
            external_message_id: External message ID (for deduplication)
            contact_name: Contact display name
            contact_data: Contact metadata
            message_metadata: Message metadata
            channel_type: Channel type for context (telegram, whatsapp, etc.)

        Returns:
            Dict with processing results and created entities

        Raises:
            MaintenanceModeError: If system is in maintenance mode
            DuplicateMessageError: If message is duplicate
            TierLimitError: If workspace limits exceeded
            BlockedContactError: If contact is blocked
            OutsideBusinessHoursError: If outside hours with inform_and_pause behavior
        """
        # 1. Check maintenance mode (highest priority)
        is_maintenance, maintenance_message = await self.is_maintenance_mode()
        if is_maintenance:
            raise MaintenanceModeError(maintenance_message)

        # 2. Check for duplicate messages
        if await self.check_message_duplicate(workspace_id, external_message_id):
            raise DuplicateMessageError(f"Message {external_message_id} already processed")

        # 3. Validate processing limits
        await self.validate_processing_limits(workspace_id)

        # Resolve channel_type if not provided
        if channel_type is None:
            ch_result = await self.db.execute(
                select(Channel.type).where(Channel.id == channel_id)
            )
            channel_type = ch_result.scalar_one_or_none() or "unknown"

        # 4. Get or create contact
        contact = await self.get_or_create_contact(
            workspace_id=workspace_id,
            channel_id=channel_id,
            external_contact_id=external_contact_id,
            contact_name=contact_name,
            contact_data=contact_data,
            channel_type=channel_type,
        )

        # 4.5 Block check — create audit message + auto-reply, then halt
        if contact.is_blocked:
            conversation = await self.get_or_create_conversation(
                workspace_id=workspace_id,
                contact_id=str(contact.id),
                channel_id=channel_id,
                channel_type=channel_type,
            )
            await self.create_message(
                conversation_id=str(conversation.id),
                content=content,
                role="customer",
                channel_type=channel_type,
                external_message_id=external_message_id,
                metadata=message_metadata,
            )
            await self.create_message(
                conversation_id=str(conversation.id),
                content="We're unable to process your message at this time.",
                role="assistant",
                channel_type=channel_type,
            )
            raise BlockedContactError("Contact is blocked")

        # 5. Get or create conversation
        conversation = await self.get_or_create_conversation(
            workspace_id=workspace_id,
            contact_id=str(contact.id),
            channel_id=channel_id,
            channel_type=channel_type,
        )

        # 5.5 Business hours check
        try:
            from app.services.business_hours_service import is_within_business_hours, get_outside_hours_behavior
            is_open, outside_msg = await is_within_business_hours(workspace_id, self.db)
            if not is_open and outside_msg:
                behavior = await get_outside_hours_behavior(workspace_id, self.db)
                # Always persist customer message for audit trail
                await self.create_message(
                    conversation_id=str(conversation.id),
                    content=content,
                    role="customer",
                    channel_type=channel_type,
                    external_message_id=external_message_id,
                    metadata=message_metadata,
                )
                # Send outside-hours auto-reply
                await self.create_message(
                    conversation_id=str(conversation.id),
                    content=outside_msg,
                    role="assistant",
                    channel_type=channel_type,
                )
                if behavior == "inform_and_pause":
                    conversation.status = "paused"
                    await self.db.commit()
                    raise OutsideBusinessHoursError(outside_msg)
                # inform_and_continue: fall through so AI also responds
        except (ImportError, OutsideBusinessHoursError):
            raise
        except Exception:
            pass  # business_hours_service not yet configured — skip silently

        # 6. If media message, download and store before creating DB record
        media_url = None
        media_size = None
        if media_id and channel_type == "whatsapp":
            try:
                from app.services.r2_storage import download_and_store_whatsapp_media
                from app.services.encryption import decrypt_credential
                ch_result = await self.db.execute(
                    select(Channel).where(Channel.id == channel_id)
                )
                ch = ch_result.scalar_one_or_none()
                if ch and ch.config:
                    encrypted_token = ch.config.get("access_token")
                    if encrypted_token:
                        access_token = decrypt_credential(encrypted_token)
                        stored = await download_and_store_whatsapp_media(
                            media_id=media_id,
                            access_token=access_token,
                            workspace_id=str(workspace_id),
                        )
                        media_url = stored["url"]
                        media_size = stored["size_bytes"]
                        if not media_mime_type:
                            media_mime_type = stored["mime_type"]
                        if not media_filename:
                            media_filename = stored.get("filename")
            except Exception:
                pass  # store without media URL if download fails

        # 7. Create message
        message = await self.create_message(
            conversation_id=str(conversation.id),
            content=content,
            role="customer",
            channel_type=channel_type,
            external_message_id=external_message_id,
            metadata=message_metadata,
            msg_type=msg_type,
            media_url=media_url,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
            media_size=media_size,
            location_lat=location_lat,
            location_lng=location_lng,
            location_name=location_name,
        )

        return {
            "contact": contact,
            "conversation": conversation,
            "message": message,
            "workspace_id": workspace_id,
            "channel_id": channel_id
        }


# ─── Convenience Functions ────────────────────────────────────────────────────

async def process_incoming_message(
    db: AsyncSession,
    workspace_id: str,
    channel_id: str,
    external_contact_id: str,
    content: Optional[str] = None,
    external_message_id: Optional[str] = None,
    contact_name: Optional[str] = None,
    contact_data: Optional[Dict[str, Any]] = None,
    message_metadata: Optional[Dict[str, Any]] = None,
    channel_type: Optional[str] = None,
    msg_type: str = "text",
    media_id: Optional[str] = None,
    media_mime_type: Optional[str] = None,
    media_filename: Optional[str] = None,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
    location_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function to process an incoming message

    Returns:
        Processing results with created entities

    Raises:
        MessageProcessingError: If processing fails
    """
    processor = MessageProcessor(db)

    result = await processor.preprocess_message(
        workspace_id=workspace_id,
        channel_id=channel_id,
        external_contact_id=external_contact_id,
        content=content,
        external_message_id=external_message_id,
        contact_name=contact_name,
        contact_data=contact_data,
        message_metadata=message_metadata,
        channel_type=channel_type,
        msg_type=msg_type,
        media_id=media_id,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
        location_lat=location_lat,
        location_lng=location_lng,
        location_name=location_name,
    )

    # Fire outbound webhook event (fire-and-forget)
    try:
        import asyncio
        from app.services.outbound_webhook_service import trigger_event
        asyncio.create_task(trigger_event(
            db=db,
            workspace_id=workspace_id,
            event_type="message.received",
            payload={
                "workspace_id": workspace_id,
                "conversation_id": str(result["conversation"].id),
                "message_id": str(result["message"].id),
                "content": content,
                "channel_id": channel_id,
            }
        ))
    except Exception:
        pass

    return result


async def check_system_maintenance(db: AsyncSession) -> Tuple[bool, Optional[str]]:
    """
    Check if system is in maintenance mode

    Returns:
        Tuple of (is_maintenance, maintenance_message)
    """
    processor = MessageProcessor(db)
    return await processor.is_maintenance_mode()
