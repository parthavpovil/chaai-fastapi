"""
WebSocket Event Broadcasting Service
Handles real-time event broadcasting with workspace isolation
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.services.websocket_manager import websocket_manager
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.agent import Agent
from app.models.contact import Contact


class WebSocketEventBroadcaster:
    """
    Service for broadcasting real-time events via WebSocket
    Maintains workspace isolation for all events
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def broadcast_escalation_event(
        self,
        workspace_id: str,
        conversation_id: str,
        escalation_reason: str,
        priority: str = "medium",
        classification_data: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Broadcast escalation event to workspace connections
        
        Args:
            workspace_id: Workspace ID
            conversation_id: Conversation ID
            escalation_reason: Reason for escalation
            priority: Escalation priority level
            classification_data: Optional classification metadata
        
        Returns:
            Number of connections that received the event
        """
        # Get conversation details for context
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
            .options(
                selectinload(Conversation.contact)
            )
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            return 0
        
        event_data = {
            "type": "escalation",
            "conversation_id": conversation_id,
            "escalation_reason": escalation_reason,
            "priority": priority,
            "contact_name": conversation.contact.name if conversation.contact else "Unknown",
            "channel_type": conversation.channel_type,
            "escalated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add classification data if available
        if classification_data:
            event_data["classification"] = {
                "confidence": classification_data.get("confidence", 0.0),
                "category": classification_data.get("category", "unknown"),
                "keywords_found": classification_data.get("keywords_found", [])
            }
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
    
    async def broadcast_agent_claim_event(
        self,
        workspace_id: str,
        conversation_id: str,
        agent_id: str
    ) -> int:
        """
        Broadcast agent claim event to workspace connections
        
        Args:
            workspace_id: Workspace ID
            conversation_id: Conversation ID
            agent_id: Agent ID who claimed the conversation
        
        Returns:
            Number of connections that received the event
        """
        # Get agent details
        from sqlalchemy import select
        
        result = await self.db.execute(
            select(Agent.name, Agent.email)
            .where(Agent.id == agent_id)
            .where(Agent.workspace_id == workspace_id)
        )
        agent = result.first()
        
        if not agent:
            return 0
        
        event_data = {
            "type": "agent_claim",
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "agent_name": agent.name,
            "agent_email": agent.email,
            "claimed_at": datetime.now(timezone.utc).isoformat()
        }
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
    
    async def broadcast_new_message_event(
        self,
        workspace_id: str,
        conversation_id: str,
        message_id: str,
        exclude_connection_id: Optional[str] = None
    ) -> int:
        """
        Broadcast new message event to workspace connections
        
        Args:
            workspace_id: Workspace ID
            conversation_id: Conversation ID
            message_id: Message ID
            exclude_connection_id: Optional connection ID to exclude from broadcast
        
        Returns:
            Number of connections that received the event
        """
        # Get message details
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        logger.info(f"🔔 broadcast_new_message_event called: workspace_id={workspace_id}, conversation_id={conversation_id}, message_id={message_id}")
        
        result = await self.db.execute(
            select(Message)
            .where(Message.id == message_id)
            .options(selectinload(Message.conversation))
        )
        message = result.scalar_one_or_none()
        
        if not message:
            logger.warning(f"❌ Message not found: message_id={message_id}")
            return 0
            
        if str(message.conversation.workspace_id) != str(workspace_id):
            logger.warning(f"❌ Workspace mismatch: message.conversation.workspace_id={message.conversation.workspace_id}, expected={workspace_id}")
            return 0
        
        event_data = {
            "type": "new_message",
            "conversation_id": conversation_id,
            "message_id": message_id,
            "role": message.role,
            "content": message.content,
            "channel_type": message.channel_type,
            "created_at": message.created_at.isoformat()
        }
        
        # Add metadata if available
        if message.extra_data:
            event_data["metadata"] = message.extra_data
        
        logger.info(f"📤 Broadcasting to workspace {workspace_id}: {event_data['type']}")
        sent_count = await websocket_manager.broadcast_to_workspace(
            workspace_id, 
            event_data, 
            exclude_connection_id
        )
        logger.info(f"✅ Broadcast sent to {sent_count} connections")
        return sent_count
    
    async def broadcast_conversation_status_change(
        self,
        workspace_id: str,
        conversation_id: str,
        old_status: str,
        new_status: str,
        agent_id: Optional[str] = None
    ) -> int:
        """
        Broadcast conversation status change event
        
        Args:
            workspace_id: Workspace ID
            conversation_id: Conversation ID
            old_status: Previous status
            new_status: New status
            agent_id: Optional agent ID if assigned
        
        Returns:
            Number of connections that received the event
        """
        event_data = {
            "type": "conversation_status_change",
            "conversation_id": conversation_id,
            "old_status": old_status,
            "new_status": new_status,
            "changed_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add agent info if assigned
        if agent_id:
            from sqlalchemy import select
            
            result = await self.db.execute(
                select(Agent.name, Agent.email)
                .where(Agent.id == agent_id)
                .where(Agent.workspace_id == workspace_id)
            )
            agent = result.first()
            
            if agent:
                event_data["agent"] = {
                    "agent_id": agent_id,
                    "agent_name": agent.name,
                    "agent_email": agent.email
                }
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
    
    async def broadcast_agent_status_change(
        self,
        workspace_id: str,
        agent_id: str,
        is_active: bool,
        status_reason: Optional[str] = None
    ) -> int:
        """
        Broadcast agent status change event
        
        Args:
            workspace_id: Workspace ID
            agent_id: Agent ID
            is_active: Whether agent is now active
            status_reason: Optional reason for status change
        
        Returns:
            Number of connections that received the event
        """
        # Get agent details
        from sqlalchemy import select
        
        result = await self.db.execute(
            select(Agent.name, Agent.email)
            .where(Agent.id == agent_id)
            .where(Agent.workspace_id == workspace_id)
        )
        agent = result.first()
        
        if not agent:
            return 0
        
        event_data = {
            "type": "agent_status_change",
            "agent_id": agent_id,
            "agent_name": agent.name,
            "agent_email": agent.email,
            "is_active": is_active,
            "status": "active" if is_active else "inactive",
            "changed_at": datetime.now(timezone.utc).isoformat()
        }
        
        if status_reason:
            event_data["reason"] = status_reason
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
    
    async def broadcast_document_processing_event(
        self,
        workspace_id: str,
        document_id: str,
        status: str,
        filename: str,
        error_message: Optional[str] = None
    ) -> int:
        """
        Broadcast document processing status event
        
        Args:
            workspace_id: Workspace ID
            document_id: Document ID
            status: Processing status ("processing", "completed", "failed")
            filename: Document filename
            error_message: Optional error message for failed status
        
        Returns:
            Number of connections that received the event
        """
        event_data = {
            "type": "document_processing",
            "document_id": document_id,
            "filename": filename,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        if error_message:
            event_data["error"] = error_message
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
    
    async def broadcast_system_notification(
        self,
        workspace_id: str,
        notification_type: str,
        title: str,
        message: str,
        priority: str = "info",
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Broadcast system notification to workspace
        
        Args:
            workspace_id: Workspace ID
            notification_type: Type of notification
            title: Notification title
            message: Notification message
            priority: Priority level ("info", "warning", "error")
            metadata: Optional additional metadata
        
        Returns:
            Number of connections that received the event
        """
        event_data = {
            "type": "system_notification",
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "priority": priority,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if metadata:
            event_data["metadata"] = metadata
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
    
    async def broadcast_workspace_stats_update(
        self,
        workspace_id: str,
        stats: Dict[str, Any]
    ) -> int:
        """
        Broadcast workspace statistics update
        
        Args:
            workspace_id: Workspace ID
            stats: Statistics data
        
        Returns:
            Number of connections that received the event
        """
        event_data = {
            "type": "workspace_stats_update",
            "stats": stats,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        return await websocket_manager.broadcast_to_workspace(workspace_id, event_data)


# ─── Event Broadcasting Integration ───────────────────────────────────────────

async def notify_escalation(
    db: AsyncSession,
    workspace_id: str,
    conversation_id: str,
    escalation_reason: str,
    priority: str = "medium",
    classification_data: Optional[Dict[str, Any]] = None
) -> int:
    """
    Notify workspace about escalation via WebSocket
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        escalation_reason: Escalation reason
        priority: Priority level
        classification_data: Classification metadata
    
    Returns:
        Number of connections notified
    """
    broadcaster = WebSocketEventBroadcaster(db)
    return await broadcaster.broadcast_escalation_event(
        workspace_id, conversation_id, escalation_reason, priority, classification_data
    )


async def notify_agent_claim(
    db: AsyncSession,
    workspace_id: str,
    conversation_id: str,
    agent_id: str
) -> int:
    """
    Notify workspace about agent claiming conversation
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        agent_id: Agent ID
    
    Returns:
        Number of connections notified
    """
    broadcaster = WebSocketEventBroadcaster(db)
    return await broadcaster.broadcast_agent_claim_event(workspace_id, conversation_id, agent_id)


async def notify_new_message(
    db: AsyncSession,
    workspace_id: str,
    conversation_id: str,
    message_id: str,
    exclude_connection_id: Optional[str] = None
) -> int:
    """
    Notify workspace about new message
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        message_id: Message ID
        exclude_connection_id: Connection to exclude from notification
    
    Returns:
        Number of connections notified
    """
    logger.info(f"🔔 notify_new_message called: workspace_id={workspace_id}, conversation_id={conversation_id}, message_id={message_id}")
    broadcaster = WebSocketEventBroadcaster(db)
    result = await broadcaster.broadcast_new_message_event(
        workspace_id, conversation_id, message_id, exclude_connection_id
    )
    logger.info(f"📊 notify_new_message result: {result} connections notified")
    return result


async def notify_agent_status_change(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    status: str
) -> int:
    """Broadcast agent availability status change to workspace."""
    return await websocket_manager.broadcast_to_workspace(
        workspace_id,
        {
            "type": "agent_status",
            "agent_id": agent_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


async def notify_message_status_update(
    db: AsyncSession,
    workspace_id: str,
    message_id: str,
    whatsapp_msg_id: str,
    status: str,
    timestamp: str
) -> int:
    """Push delivery receipt update to dashboard in real time."""
    return await websocket_manager.broadcast_to_workspace(
        workspace_id,
        {
            "type": "message_status_update",
            "message_id": message_id,
            "whatsapp_message_id": whatsapp_msg_id,
            "status": status,
            "timestamp": timestamp
        }
    )


async def notify_conversation_status_change(
    db: AsyncSession,
    workspace_id: str,
    conversation_id: str,
    old_status: str,
    new_status: str,
    agent_id: Optional[str] = None
) -> int:
    """
    Notify workspace about conversation status change
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        old_status: Previous status
        new_status: New status
        agent_id: Optional agent ID
    
    Returns:
        Number of connections notified
    """
    broadcaster = WebSocketEventBroadcaster(db)
    return await broadcaster.broadcast_conversation_status_change(
        workspace_id, conversation_id, old_status, new_status, agent_id
    )


# ─── Customer (Widget) Notification Helpers ───────────────────────────────────
# These push events directly to the customer's WS session (not to agents).
# All are fire-and-forget — callers never check return values.

async def notify_customer_new_message(
    db: AsyncSession,
    workspace_id: str,
    session_token: str,
    message_id: str,
) -> bool:
    """
    Push a new_message event to the customer's WS connection.
    Called after AI reply or human-agent reply is saved.
    Returns True if sent, False if no active WS connection (graceful).
    """
    try:
        from sqlalchemy import select
        from app.models.message import Message
        from app.services.websocket_manager import customer_websocket_manager

        result = await db.execute(select(Message).where(Message.id == message_id))
        message = result.scalar_one_or_none()
        if not message:
            return False

        event = {
            "type": "new_message",
            "message_id": str(message.id),
            "role": message.role,
            "content": message.content,
            "msg_type": message.msg_type or "text",
            "media_url": message.media_url,
            "media_filename": message.media_filename,
            "media_mime_type": message.media_mime_type,
            "created_at": message.created_at.isoformat(),
        }

        return await customer_websocket_manager.send_to_session(
            workspace_id, session_token, event
        )
    except Exception as e:
        logger.error(f"notify_customer_new_message error: {e}", exc_info=True)
        return False


async def notify_customer_status_change(
    workspace_id: str,
    session_token: str,
    new_status: str,
    agent_name: Optional[str] = None,
) -> bool:
    """
    Push a conversation_status_changed event to the customer's WS connection.
    Called on escalation, agent assignment, or resolution.
    """
    try:
        from app.services.websocket_manager import customer_websocket_manager

        event = {
            "type": "conversation_status_changed",
            "new_status": new_status,
            "agent_name": agent_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return await customer_websocket_manager.send_to_session(
            workspace_id, session_token, event
        )
    except Exception as e:
        logger.error(f"notify_customer_status_change error: {e}", exc_info=True)
        return False


async def notify_customer_csat_prompt(
    workspace_id: str,
    session_token: str,
    token: str,
) -> bool:
    """
    Push a csat_prompt event to the customer's WS connection.
    Called when a webchat conversation is resolved.
    """
    try:
        from app.services.websocket_manager import customer_websocket_manager

        event = {
            "type": "csat_prompt",
            "token": token,
            "expires_in_hours": 72,
        }

        return await customer_websocket_manager.send_to_session(
            workspace_id, session_token, event
        )
    except Exception as e:
        logger.error(f"notify_customer_csat_prompt error: {e}", exc_info=True)
        return False