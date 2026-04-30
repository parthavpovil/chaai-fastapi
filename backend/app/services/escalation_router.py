"""
Escalation Workflow Routing Service
Handles escalation workflow, agent notifications, and customer acknowledgments
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

logger = logging.getLogger(__name__)

from app.models.workspace import Workspace
from app.models.conversation import Conversation
from app.models.agent import Agent
from app.models.message import Message
from app.services.conversation_manager import ConversationManager
from app.services.escalation_classifier import EscalationClassifier
from app.services import assignment_service


class EscalationRoutingError(Exception):
    """Base exception for escalation routing errors"""
    pass


class EscalationRouter:
    """
    Escalation workflow routing service
    Manages escalation process, agent notifications, and customer communication
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_manager = ConversationManager(db)
        self.classifier = EscalationClassifier(db)
    
    async def get_available_agents(self, workspace_id: str) -> List[Agent]:
        """
        Get available agents for a workspace
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            List of active agents
        """
        result = await self.db.execute(
            select(Agent)
            .where(Agent.workspace_id == workspace_id)
            .where(Agent.is_active == True)
            .order_by(Agent.created_at)  # FIFO assignment
        )
        return result.scalars().all()
    
    async def get_workspace_owner_email(self, workspace_id: str) -> Optional[str]:
        """
        Get workspace owner email for notifications
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            Owner email or None
        """
        from app.models.user import User
        
        result = await self.db.execute(
            select(User.email)
            .join(Workspace, Workspace.owner_id == User.id)
            .where(Workspace.id == workspace_id)
        )
        return result.scalar_one_or_none()
    
    async def create_escalation_message(
        self,
        conversation_id: str,
        escalation_reason: str,
        classification_data: Dict[str, Any]
    ) -> Message:
        """
        Create system message documenting the escalation
        
        Args:
            conversation_id: Conversation ID
            escalation_reason: Reason for escalation
            classification_data: Classification metadata
        
        Returns:
            Created system message
        """
        if escalation_reason == "direct_routing":
            escalation_content = "Conversation routed directly to human agent (AI disabled in workspace settings)"
        else:
            escalation_content = f"Conversation escalated: {escalation_reason}"
        
        message = Message(
            conversation_id=conversation_id,
            content=escalation_content,
            role="system",
            channel_type="system",
            extra_data={
                "escalation": True,
                "escalation_reason": escalation_reason,
                "classification": classification_data,
                "escalated_at": datetime.now(timezone.utc).isoformat()
            }
        )
        
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        
        return message
    
    async def send_customer_acknowledgment(
        self,
        conversation_id: str,
        has_agents: bool,
        workspace_id: str
    ) -> Message:
        """
        Send acknowledgment message to customer
        
        Args:
            conversation_id: Conversation ID
            has_agents: Whether workspace has available agents
            workspace_id: Workspace ID for custom messages
        
        Returns:
            Created acknowledgment message
        """
        # Fetch workspace to use custom messages if configured
        ws_result = await self.db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        ws = ws_result.scalar_one_or_none()

        default_with_agents = (
            "Thank you for your message. I've escalated your request to one of our "
            "human agents who will assist you shortly. Please wait for their response."
        )
        default_without_agents = (
            "Thank you for your message. I've forwarded your request to our support team. "
            "Someone will get back to you as soon as possible via email or through this chat."
        )

        if has_agents:
            content = (
                ws.escalation_message_with_agents
                if ws and ws.escalation_message_with_agents
                else default_with_agents
            )
        else:
            content = (
                ws.escalation_message_without_agents
                if ws and ws.escalation_message_without_agents
                else default_without_agents
            )

        message = Message(
            conversation_id=conversation_id,
            content=content,
            role="assistant",
            channel_type="system",
            extra_data={
                "escalation_acknowledgment": True,
                "has_agents": has_agents
            }
        )
        
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        
        # Broadcast escalation acknowledgment message via websocket
        from app.services.websocket_events import notify_new_message
        await notify_new_message(
            db=self.db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=str(message.id),
        )
        
        return message
    
    async def notify_agents_via_websocket(
        self,
        workspace_id: str,
        conversation_id: str,
        escalation_data: Dict[str, Any]
    ) -> bool:
        """
        Notify available agents via WebSocket
        
        Args:
            workspace_id: Workspace ID
            conversation_id: Conversation ID
            escalation_data: Escalation metadata
        
        Returns:
            True if notifications sent successfully
        """
        try:
            from app.services.websocket_events import notify_escalation
            
            # Broadcast escalation event to workspace connections
            connections_notified = await notify_escalation(
                db=self.db,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                escalation_reason=escalation_data.get("reason", "Unknown"),
                priority=escalation_data.get("priority", "medium"),
                classification_data=escalation_data.get("classification")
            )
            
            logger.info("WebSocket escalation notification sent to %d connections", connections_notified)
            return connections_notified > 0

        except Exception:
            logger.warning("WebSocket escalation notification failed", exc_info=True)
            return False
    
    async def send_email_alert(
        self,
        workspace_id: str,
        owner_email: str,
        conversation_id: str,
        escalation_data: Dict[str, Any]
    ) -> bool:
        """
        Send email alert to workspace owner
        
        Args:
            workspace_id: Workspace ID
            owner_email: Owner email address
            conversation_id: Conversation ID
            escalation_data: Escalation metadata
        
        Returns:
            True if email sent successfully
        """
        try:
            from app.services.email_service import EmailService
            
            email_service = EmailService()
            
            # Send escalation alert email
            success = await email_service.send_escalation_alert(
                to_email=owner_email,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                escalation_reason=escalation_data.get("reason", "Unknown"),
                priority=escalation_data.get("priority", "medium"),
                classification_data=escalation_data.get("classification")
            )
            
            if success:
                logger.info("Escalation email alert sent to %s", owner_email)
            else:
                logger.warning("Escalation email alert delivery failed for %s", owner_email)

            return success

        except Exception:
            logger.error("Email escalation alert raised an exception", exc_info=True)
            return False
    
    async def process_escalation(
        self,
        conversation_id: str,
        workspace_id: str,
        escalation_reason: str,
        classification_data: Dict[str, Any],
        priority: str = "medium"
    ) -> Dict[str, Any]:
        """
        Complete escalation workflow processing
        
        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID
            escalation_reason: Reason for escalation
            classification_data: Classification metadata
            priority: Escalation priority level
        
        Returns:
            Escalation processing results
        
        Raises:
            EscalationRoutingError: If escalation processing fails
        """
        try:
            # 1. Update conversation status to escalated
            conversation = await self.conversation_manager.escalate_conversation(
                conversation_id, workspace_id, escalation_reason
            )
            
            if not conversation:
                raise EscalationRoutingError("Conversation not found or access denied")
            
            # 2. Create escalation system message
            escalation_message = await self.create_escalation_message(
                conversation_id, escalation_reason, classification_data
            )
            
            # 3. Get available agents and assign via rules (or FIFO fallback)
            available_agents = await self.get_available_agents(workspace_id)
            has_agents = len(available_agents) > 0

            assigned_agent_id = None
            if has_agents:
                # Try assignment rules first
                matched_rule = await assignment_service.evaluate_rules(
                    self.db, workspace_id, escalation_reason, conversation.channel_type
                )
                if matched_rule:
                    assigned_agent_id = await assignment_service.assign_by_rule(
                        self.db, matched_rule, conversation_id
                    )

                # Fall back to FIFO (first agent in created_at order)
                if not assigned_agent_id:
                    assigned_agent_id = available_agents[0].id

                # Persist assignment on conversation
                if assigned_agent_id:
                    conversation.assigned_agent_id = assigned_agent_id
                    await self.db.commit()

            # 4. Send customer acknowledgment
            acknowledgment_message = await self.send_customer_acknowledgment(
                conversation_id, has_agents, workspace_id
            )
            
            # 5. Notify agents or send email alert
            notifications_sent = False
            email_sent = False
            
            escalation_data = {
                "conversation_id": conversation_id,
                "reason": escalation_reason,
                "priority": priority,
                "classification": classification_data
            }
            
            if has_agents:
                # Notify agents via WebSocket
                try:
                    notifications_sent = await self.notify_agents_via_websocket(
                        workspace_id, conversation_id, escalation_data
                    )
                except Exception:
                    logger.warning("WebSocket agent notification failed", exc_info=True)
                    notifications_sent = False
            else:
                # Send email alert to workspace owner (only if enabled in workspace settings)
                ws_result = await self.db.execute(
                    select(Workspace).where(Workspace.id == workspace_id)
                )
                ws = ws_result.scalar_one_or_none()
                email_enabled = ws.escalation_email_enabled if ws else True
                if email_enabled:
                    owner_email = await self.get_workspace_owner_email(workspace_id)
                    if owner_email:
                        try:
                            email_sent = await self.send_email_alert(
                                workspace_id, owner_email, conversation_id, escalation_data
                            )
                        except Exception:
                            logger.error("Email alert failed during process_escalation", exc_info=True)
                            email_sent = False
            
            result = {
                "success": True,
                "conversation_id": conversation_id,
                "escalation_reason": escalation_reason,
                "priority": priority,
                "has_agents": has_agents,
                "available_agents_count": len(available_agents),
                "assigned_agent_id": str(assigned_agent_id) if assigned_agent_id else None,
                "notifications_sent": notifications_sent,
                "email_sent": email_sent,
                "escalation_message_id": escalation_message.id,
                "acknowledgment_message_id": acknowledgment_message.id,
                "escalated_at": datetime.now(timezone.utc).isoformat()
            }

            # Fire outbound webhook event (fire-and-forget)
            try:
                import asyncio
                from app.services.outbound_webhook_service import trigger_event
                asyncio.create_task(trigger_event(
                    db=self.db,
                    workspace_id=workspace_id,
                    event_type="conversation.escalated",
                    payload={
                        "workspace_id": workspace_id,
                        "conversation_id": conversation_id,
                        "escalation_reason": escalation_reason,
                        "priority": priority,
                        "escalated_at": result["escalated_at"],
                    }
                ))
            except Exception:
                logger.warning("Failed to schedule outbound webhook for conversation.escalated", exc_info=True)

            # Push escalation status to customer WS if this is a webchat conversation
            try:
                from uuid import UUID as _UUID
                from sqlalchemy import select
                from app.models.contact import Contact
                from app.models.conversation import Conversation
                from app.services.websocket_events import notify_customer_status_change
                cust_row = await self.db.execute(
                    select(Conversation, Contact)
                    .join(Contact, Contact.id == Conversation.contact_id)
                    .where(Conversation.id == _UUID(conversation_id))
                )
                cust = cust_row.first()
                if cust and cust[0].channel_type == "webchat":
                    await notify_customer_status_change(
                        workspace_id=workspace_id,
                        session_token=cust[1].external_id,
                        new_status="escalated",
                    )
            except Exception:
                logger.warning("Failed to send WebSocket escalation status to customer", exc_info=True)

            return result
            
        except Exception as e:
            raise EscalationRoutingError(f"Escalation processing failed: {str(e)}")
    
    async def auto_escalate_if_needed(
        self,
        conversation_id: str,
        workspace_id: str,
        message_content: str,
        confidence_threshold: float = 0.7
    ) -> Optional[Dict[str, Any]]:
        """
        Automatically escalate message if classification indicates escalation needed

        Args:
            conversation_id: Conversation ID
            workspace_id: Workspace ID
            message_content: Message content to classify
            confidence_threshold: Minimum confidence for auto-escalation

        Returns:
            Escalation results if escalated, None if not escalated
        """
        try:
            # Load workspace escalation config
            ws_result = await self.db.execute(
                select(Workspace).where(Workspace.id == workspace_id)
            )
            workspace = ws_result.scalar_one_or_none()
            workspace_keywords = workspace.escalation_keywords if workspace else None
            sensitivity = (workspace.escalation_sensitivity or "medium") if workspace else "medium"

            # Classify message for escalation
            classification = await self.classifier.classify_message(
                message_content, conversation_id,
                workspace_keywords=workspace_keywords,
                sensitivity=sensitivity
            )
            
            # Trust the classifier's decision — it already applied the workspace
            # sensitivity threshold internally. The redundant confidence gate here
            # was silently blocking keyword-detected escalations.
            if not classification['should_escalate']:
                return None
            
            # Get priority level
            priority = self.classifier.get_escalation_priority(classification)
            
            # Use escalation_type ("explicit" or "implicit") per requirements 4.2 and 4.3
            escalation_type = classification.get('escalation_type', 'unknown')
            
            # Process escalation
            return await self.process_escalation(
                conversation_id=conversation_id,
                workspace_id=workspace_id,
                escalation_reason=escalation_type,  # Use "explicit" or "implicit" per requirements
                classification_data=classification,
                priority=priority
            )
            
        except Exception:
            logger.warning("Auto-escalation failed unexpectedly", exc_info=True)
            return None
    
    async def get_escalated_conversations(
        self,
        workspace_id: str,
        priority: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get escalated conversations for a workspace
        
        Args:
            workspace_id: Workspace ID
            priority: Optional priority filter
            limit: Maximum conversations to return
        
        Returns:
            List of escalated conversations with metadata
        """
        conversations = await self.conversation_manager.get_workspace_conversations(
            workspace_id, status="escalated", limit=limit
        )
        
        escalated_conversations = []
        
        for conv in conversations:
            # Get escalation metadata from conversation
            escalation_metadata = conv.meta or {}
            conv_priority = escalation_metadata.get("priority", "medium")
            
            # Filter by priority if specified
            if priority and conv_priority != priority:
                continue
            
            escalated_conversations.append({
                "conversation_id": conv.id,
                "contact_name": conv.contact.name if conv.contact else "Unknown",
                "channel_type": conv.channel_type,
                "escalated_at": escalation_metadata.get("escalated_at"),
                "escalation_reason": escalation_metadata.get("escalation_reason", "Unknown"),
                "priority": conv_priority,
                "updated_at": conv.updated_at.isoformat()
            })
        
        return escalated_conversations


# ─── Convenience Functions ────────────────────────────────────────────────────

async def escalate_conversation(
    db: AsyncSession,
    conversation_id: str,
    workspace_id: str,
    reason: str,
    priority: str = "medium"
) -> Dict[str, Any]:
    """
    Convenience function to manually escalate a conversation
    
    Args:
        db: Database session
        conversation_id: Conversation ID
        workspace_id: Workspace ID
        reason: Escalation reason
        priority: Priority level
    
    Returns:
        Escalation processing results
    """
    router = EscalationRouter(db)
    
    classification_data = {
        "should_escalate": True,
        "confidence": 1.0,
        "reason": reason,
        "category": "manual",
        "classification_method": "manual"
    }
    
    return await router.process_escalation(
        conversation_id, workspace_id, reason, classification_data, priority
    )


async def check_and_escalate_message(
    db: AsyncSession,
    conversation_id: str,
    workspace_id: str,
    message_content: str
) -> Optional[Dict[str, Any]]:
    """
    Check message for escalation and escalate if needed
    
    Args:
        db: Database session
        conversation_id: Conversation ID
        workspace_id: Workspace ID
        message_content: Message content
    
    Returns:
        Escalation results if escalated, None otherwise
    """
    router = EscalationRouter(db)
    return await router.auto_escalate_if_needed(
        conversation_id, workspace_id, message_content
    )