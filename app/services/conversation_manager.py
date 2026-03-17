"""
Conversation and Contact Management Service
Handles conversation lifecycle, contact management, and workspace isolation
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_, desc, func
from sqlalchemy.orm import selectinload

from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.agent import Agent


class ConversationManagementError(Exception):
    """Exception raised for conversation management errors"""
    pass


class ConversationManager:
    """
    Manages conversations and contacts with proper workspace isolation
    Handles conversation status transitions and agent assignments
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_workspace_conversations(
        self,
        workspace_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Conversation]:
        """
        Get conversations for a workspace with optional status filtering
        
        Args:
            workspace_id: Workspace ID
            status: Optional status filter ("active", "escalated", "agent", "closed")
            limit: Maximum number of conversations to return
            offset: Offset for pagination
        
        Returns:
            List of conversations with loaded relationships
        """
        query = select(Conversation).where(
            Conversation.workspace_id == workspace_id
        ).options(
            selectinload(Conversation.contact),
            selectinload(Conversation.channel),
            selectinload(Conversation.agent)
        ).order_by(desc(Conversation.updated_at))
        
        if status:
            query = query.where(Conversation.status == status)
        
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_conversation_by_id(
        self,
        conversation_id: str,
        workspace_id: str
    ) -> Optional[Conversation]:
        """
        Get conversation by ID with workspace isolation
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
        
        Returns:
            Conversation instance or None
        """
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
            .options(
                selectinload(Conversation.contact),
                selectinload(Conversation.channel),
                selectinload(Conversation.agent)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_conversation_messages(
        self,
        conversation_id: str,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Message]:
        """
        Get messages for a conversation with workspace isolation
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            limit: Maximum number of messages to return
            offset: Offset for pagination
        
        Returns:
            List of messages ordered by creation time
        """
        # Verify conversation belongs to workspace
        conversation = await self.get_conversation_by_id(conversation_id, workspace_id)
        if not conversation:
            return []
        
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
    
    async def update_conversation_status(
        self,
        conversation_id: str,
        workspace_id: str,
        new_status: str,
        agent_id: Optional[str] = None
    ) -> Optional[Conversation]:
        """
        Update conversation status with workspace isolation
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            new_status: New status ("active", "escalated", "agent", "closed")
            agent_id: Optional agent ID for "agent" status
        
        Returns:
            Updated conversation or None if not found
        """
        # Verify conversation belongs to workspace
        conversation = await self.get_conversation_by_id(conversation_id, workspace_id)
        if not conversation:
            return None
        
        update_data = {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc)
        }
        
        if new_status == "agent" and agent_id:
            update_data["agent_id"] = agent_id
        elif new_status != "agent":
            update_data["agent_id"] = None
        
        stmt = update(Conversation).where(
            Conversation.id == conversation_id
        ).values(**update_data).returning(Conversation)
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        updated_conversation = result.scalar_one_or_none()
        if updated_conversation:
            await self.db.refresh(updated_conversation)
        
        return updated_conversation
    
    async def escalate_conversation(
        self,
        conversation_id: str,
        workspace_id: str,
        escalation_reason: Optional[str] = None
    ) -> Optional[Conversation]:
        """
        Escalate conversation to human agents
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            escalation_reason: Optional reason for escalation
        
        Returns:
            Updated conversation or None if not found
        """
        conversation = await self.update_conversation_status(
            conversation_id, workspace_id, "escalated"
        )
        
        if conversation and escalation_reason:
            # Add escalation metadata
            metadata = conversation.metadata or {}
            metadata["escalation_reason"] = escalation_reason
            metadata["escalated_at"] = datetime.now(timezone.utc).isoformat()
            
            stmt = update(Conversation).where(
                Conversation.id == conversation_id
            ).values(metadata=metadata)
            
            await self.db.execute(stmt)
            await self.db.commit()
        
        return conversation
    
    async def assign_agent_to_conversation(
        self,
        conversation_id: str,
        workspace_id: str,
        agent_id: str
    ) -> Optional[Conversation]:
        """
        Assign an agent to an escalated conversation
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            agent_id: Agent ID
        
        Returns:
            Updated conversation or None if not found/invalid
        """
        # Verify agent belongs to workspace and is active
        agent_result = await self.db.execute(
            select(Agent)
            .where(Agent.id == agent_id)
            .where(Agent.workspace_id == workspace_id)
            .where(Agent.is_active == True)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            return None
        
        return await self.update_conversation_status(
            conversation_id, workspace_id, "agent", agent_id
        )
    
    async def get_agent_conversations(
        self,
        agent_id: str,
        workspace_id: str,
        limit: int = 20
    ) -> List[Conversation]:
        """
        Get conversations assigned to a specific agent
        
        Args:
            agent_id: Agent ID
            workspace_id: Workspace ID for isolation
            limit: Maximum number of conversations to return
        
        Returns:
            List of conversations assigned to the agent
        """
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.agent_id == agent_id)
            .where(Conversation.workspace_id == workspace_id)
            .where(Conversation.status == "agent")
            .options(
                selectinload(Conversation.contact),
                selectinload(Conversation.channel)
            )
            .order_by(desc(Conversation.updated_at))
            .limit(limit)
        )
        return result.scalars().all()
    
    async def close_conversation(
        self,
        conversation_id: str,
        workspace_id: str,
        closed_by: Optional[str] = None
    ) -> Optional[Conversation]:
        """
        Close a conversation
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            closed_by: Optional ID of who closed the conversation
        
        Returns:
            Updated conversation or None if not found
        """
        conversation = await self.update_conversation_status(
            conversation_id, workspace_id, "closed"
        )
        
        if conversation and closed_by:
            # Add closure metadata
            metadata = conversation.metadata or {}
            metadata["closed_by"] = closed_by
            metadata["closed_at"] = datetime.now(timezone.utc).isoformat()
            
            stmt = update(Conversation).where(
                Conversation.id == conversation_id
            ).values(metadata=metadata)
            
            await self.db.execute(stmt)
            await self.db.commit()
        
        return conversation
    
    async def get_workspace_contacts(
        self,
        workspace_id: str,
        channel_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Contact]:
        """
        Get contacts for a workspace with optional channel filtering
        
        Args:
            workspace_id: Workspace ID
            channel_id: Optional channel ID filter
            limit: Maximum number of contacts to return
            offset: Offset for pagination
        
        Returns:
            List of contacts
        """
        query = select(Contact).where(
            Contact.workspace_id == workspace_id
        ).options(
            selectinload(Contact.channel)
        ).order_by(desc(Contact.updated_at))
        
        if channel_id:
            query = query.where(Contact.channel_id == channel_id)
        
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_contact_info(
        self,
        contact_id: str,
        workspace_id: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Contact]:
        """
        Update contact information with workspace isolation
        
        Args:
            contact_id: Contact ID
            workspace_id: Workspace ID for isolation
            name: Optional new name
            metadata: Optional metadata to merge
        
        Returns:
            Updated contact or None if not found
        """
        # Verify contact belongs to workspace
        result = await self.db.execute(
            select(Contact)
            .where(Contact.id == contact_id)
            .where(Contact.workspace_id == workspace_id)
        )
        contact = result.scalar_one_or_none()
        if not contact:
            return None
        
        update_data = {"updated_at": datetime.now(timezone.utc)}
        
        if name:
            update_data["name"] = name
        
        if metadata:
            # Merge with existing metadata
            existing_metadata = contact.metadata or {}
            existing_metadata.update(metadata)
            update_data["metadata"] = existing_metadata
        
        stmt = update(Contact).where(
            Contact.id == contact_id
        ).values(**update_data).returning(Contact)
        
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.scalar_one_or_none()
    
    async def get_conversation_statistics(self, workspace_id: str) -> Dict[str, int]:
        """
        Get conversation statistics for a workspace
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            Dict with conversation counts by status
        """
        result = await self.db.execute(
            select(
                Conversation.status,
                func.count(Conversation.id).label('count')
            )
            .where(Conversation.workspace_id == workspace_id)
            .group_by(Conversation.status)
        )
        
        stats = {"active": 0, "escalated": 0, "agent": 0, "closed": 0}
        for row in result:
            stats[row.status] = row.count
        
        return stats


# ─── Convenience Functions ────────────────────────────────────────────────────

async def get_workspace_conversation_list(
    db: AsyncSession,
    workspace_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Conversation]:
    """
    Convenience function to get workspace conversations
    """
    manager = ConversationManager(db)
    return await manager.get_workspace_conversations(
        workspace_id, status, limit, offset
    )


async def escalate_conversation_by_id(
    db: AsyncSession,
    conversation_id: str,
    workspace_id: str,
    reason: Optional[str] = None
) -> Optional[Conversation]:
    """
    Convenience function to escalate a conversation
    """
    manager = ConversationManager(db)
    return await manager.escalate_conversation(conversation_id, workspace_id, reason)

    async def get_conversation_detail(
        self, 
        conversation_id: str, 
        workspace_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed conversation information with messages
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID for isolation
            
        Returns:
            Detailed conversation data or None if not found
        """
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
            .options(
                selectinload(Conversation.contact),
                selectinload(Conversation.messages).selectinload(Message.sender)
            )
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            return None
        
        # Get assigned agent info
        assigned_agent_name = None
        if conversation.assigned_agent_id:
            agent_result = await self.db.execute(
                select(Agent).where(Agent.id == conversation.assigned_agent_id)
            )
            agent = agent_result.scalar_one_or_none()
            if agent:
                assigned_agent_name = agent.name
        
        # Format messages
        messages = []
        for msg in conversation.messages:
            messages.append({
                "id": str(msg.id),
                "content": msg.content,
                "role": msg.role,
                "sender_name": msg.sender.email if msg.sender else None,
                "created_at": msg.created_at.isoformat(),
                "metadata": msg.metadata
            })
        
        return {
            "id": str(conversation.id),
            "status": conversation.status,
            "contact": {
                "id": str(conversation.contact.id),
                "name": conversation.contact.name,
                "external_id": conversation.contact.external_contact_id,
                "channel_type": conversation.channel_type,
                "metadata": conversation.contact.metadata
            },
            "assigned_agent_id": str(conversation.assigned_agent_id) if conversation.assigned_agent_id else None,
            "assigned_agent_name": assigned_agent_name,
            "escalation_reason": conversation.escalation_reason,
            "messages": messages,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat()
        }

    async def claim_conversation(
        self, 
        conversation_id: str, 
        agent_id: str, 
        workspace_id: str
    ) -> None:
        """
        Claim an escalated conversation for an agent
        
        Args:
            conversation_id: Conversation ID
            agent_id: Agent ID
            workspace_id: Workspace ID for isolation
            
        Raises:
            ConversationManagementError: If conversation cannot be claimed
        """
        # Get conversation
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            raise ConversationManagementError("Conversation not found")
        
        if conversation.status != "escalated":
            raise ConversationManagementError("Only escalated conversations can be claimed")
        
        if conversation.assigned_agent_id:
            raise ConversationManagementError("Conversation is already assigned to an agent")
        
        # Verify agent exists and is active
        agent_result = await self.db.execute(
            select(Agent)
            .where(Agent.id == agent_id)
            .where(Agent.workspace_id == workspace_id)
            .where(Agent.is_active == True)
        )
        agent = agent_result.scalar_one_or_none()
        
        if not agent:
            raise ConversationManagementError("Agent not found or inactive")
        
        # Claim conversation
        conversation.assigned_agent_id = agent_id
        conversation.status = "agent"
        conversation.updated_at = datetime.now(timezone.utc)
        
        await self.db.commit()

    async def send_agent_message(
        self, 
        conversation_id: str, 
        agent_id: str, 
        content: str, 
        workspace_id: str
    ) -> Message:
        """
        Send a message as an agent in a conversation
        
        Args:
            conversation_id: Conversation ID
            agent_id: Agent ID
            content: Message content
            workspace_id: Workspace ID for isolation
            
        Returns:
            Created message
            
        Raises:
            ConversationManagementError: If message cannot be sent
        """
        # Get conversation
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.workspace_id == workspace_id)
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            raise ConversationManagementError("Conversation not found")
        
        if conversation.assigned_agent_id != agent_id:
            raise ConversationManagementError("Agent is not assigned to this conversation")
        
        # Get agent
        agent_result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        
        if not agent:
            raise ConversationManagementError("Agent not found")
        
        # Create message
        message = Message(
            conversation_id=conversation_id,
            content=content,
            role="agent",
            sender_id=agent.user_id,
            metadata={"agent_id": str(agent_id), "agent_name": agent.name}
        )
        
        self.db.add(message)
        
        # Update conversation timestamp
        conversation.updated_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        await self.db.refresh(message)
        
        return message