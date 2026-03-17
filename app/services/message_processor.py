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
        contact_data: Optional[Dict[str, Any]] = None
    ) -> Contact:
        """
        Get existing contact or create new one
        
        Args:
            workspace_id: Workspace ID
            channel_id: Channel ID
            external_contact_id: External contact ID from platform
            contact_name: Display name for contact
            contact_data: Additional contact metadata
        
        Returns:
            Contact instance
        """
        # Try to find existing contact
        result = await self.db.execute(
            select(Contact)
            .where(Contact.workspace_id == workspace_id)
            .where(Contact.channel_id == channel_id)
            .where(Contact.external_contact_id == external_contact_id)
        )
        contact = result.scalar_one_or_none()
        
        if contact:
            return contact
        
        # Create new contact
        contact = Contact(
            workspace_id=workspace_id,
            channel_id=channel_id,
            external_contact_id=external_contact_id,
            name=contact_name or f"Contact {external_contact_id}",
            metadata=contact_data or {}
        )
        
        self.db.add(contact)
        await self.db.commit()
        await self.db.refresh(contact)
        
        return contact
    
    async def get_or_create_conversation(
        self,
        workspace_id: str,
        contact_id: str,
        channel_id: str
    ) -> Conversation:
        """
        Get existing conversation or create new one
        
        Args:
            workspace_id: Workspace ID
            contact_id: Contact ID
            channel_id: Channel ID
        
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
            status="active"
        )
        
        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)
        
        return conversation
    
    async def create_message(
        self,
        conversation_id: str,
        content: str,
        role: str = "customer",
        channel_type: str = "webchat",
        external_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        Create a new message in the conversation
        
        Args:
            conversation_id: Conversation ID
            content: Message content
            role: Role of message sender ("customer", "assistant", "agent")
            channel_type: Type of channel
            external_message_id: External message ID from platform
            metadata: Additional message metadata
        
        Returns:
            Created Message instance
        """
        message = Message(
            conversation_id=conversation_id,
            content=content,
            role=role,
            channel_type=channel_type,
            external_message_id=external_message_id,
            extra_data=metadata or {}
        )
        
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        
        return message
    
    async def preprocess_message(
        self,
        workspace_id: str,
        channel_id: str,
        external_contact_id: str,
        content: str,
        external_message_id: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_data: Optional[Dict[str, Any]] = None,
        message_metadata: Optional[Dict[str, Any]] = None
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
        
        Returns:
            Dict with processing results and created entities
        
        Raises:
            MaintenanceModeError: If system is in maintenance mode
            DuplicateMessageError: If message is duplicate
            TierLimitError: If workspace limits exceeded
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
        
        # 4. Get or create contact
        contact = await self.get_or_create_contact(
            workspace_id=workspace_id,
            channel_id=channel_id,
            external_contact_id=external_contact_id,
            contact_name=contact_name,
            contact_data=contact_data
        )
        
        # 5. Get or create conversation
        conversation = await self.get_or_create_conversation(
            workspace_id=workspace_id,
            contact_id=contact.id,
            channel_id=channel_id
        )
        
        # 6. Create message
        message = await self.create_message(
            conversation_id=str(conversation.id),
            content=content,
            role="customer",
            channel_type=channel.type if hasattr(channel, 'type') else "unknown",
            external_message_id=external_message_id,
            metadata=message_metadata
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
    content: str,
    external_message_id: Optional[str] = None,
    contact_name: Optional[str] = None,
    contact_data: Optional[Dict[str, Any]] = None,
    message_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function to process an incoming message
    
    Returns:
        Processing results with created entities
    
    Raises:
        MessageProcessingError: If processing fails
    """
    processor = MessageProcessor(db)
    
    return await processor.preprocess_message(
        workspace_id=workspace_id,
        channel_id=channel_id,
        external_contact_id=external_contact_id,
        content=content,
        external_message_id=external_message_id,
        contact_name=contact_name,
        contact_data=contact_data,
        message_metadata=message_metadata
    )


async def check_system_maintenance(db: AsyncSession) -> Tuple[bool, Optional[str]]:
    """
    Check if system is in maintenance mode
    
    Returns:
        Tuple of (is_maintenance, maintenance_message)
    """
    processor = MessageProcessor(db)
    return await processor.is_maintenance_mode()