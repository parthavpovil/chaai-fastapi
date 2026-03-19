"""
WebSocket Event Broadcasting Service
Handles real-time event broadcasting with workspace isolation
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

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
        
        result = await self.db.execute(
            select(Message)
            .where(Message.id == message_id)
            .options(selectinload(Message.conversation))
        )
        message = result.scalar_one_or_none()
        
        if not message or message.conversation.workspace_id != workspace_id:
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
        
        return await websocket_manager.broadcast_to_workspace(
            workspace_id, 
            event_data, 
            exclude_connection_id
        )
    
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
    broadcaster = WebSocketEventBroadcaster(db)
    return await broadcaster.broadcast_new_message_event(
        workspace_id, conversation_id, message_id, exclude_connection_id
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