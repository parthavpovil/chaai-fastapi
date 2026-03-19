"""
WebChat Service
Handles WebChat widget configuration and session management
"""
from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Workspace, Channel
from app.services.encryption import EncryptionService


class WebChatService:
    """Service for WebChat widget operations"""
    
    def __init__(self):
        self.encryption_service = EncryptionService()
    
    async def get_widget_config(
        self,
        db: AsyncSession,
        workspace_slug: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get widget configuration for a workspace
        
        Args:
            db: Database session
            workspace_slug: Workspace slug
            
        Returns:
            Widget configuration dict or None if not found/inactive
        """
        # Find workspace by slug
        result = await db.execute(
            select(Workspace).where(Workspace.slug == workspace_slug)
        )
        workspace = result.scalar_one_or_none()
        
        if not workspace:
            return None
        
        # Find active webchat channel
        result = await db.execute(
            select(Channel).where(
                Channel.workspace_id == workspace.id,
                Channel.type == 'webchat',
                Channel.is_active == True
            )
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            return None
        
        # Return config with widget_id
        if not channel.config:
            return None
            
        try:
            # Config is stored as JSONB, may have encrypted fields
            # For webchat, we expect the config to be directly usable
            config = dict(channel.config)
            config['widget_id'] = str(channel.id)
            return config
        except Exception:
            return None
    
    async def validate_widget_session(
        self,
        db: AsyncSession,
        widget_id: UUID,
        session_token: str
    ) -> bool:
        """
        Validate a widget session token
        
        Args:
            db: Database session
            widget_id: Widget (channel) ID
            session_token: Session token to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Basic validation - check token format
        if not session_token or len(session_token) < 10:
            return False
        
        # Check if widget exists and is active
        result = await db.execute(
            select(Channel).where(
                Channel.id == widget_id,
                Channel.type == 'webchat',
                Channel.is_active == True
            )
        )
        channel = result.scalar_one_or_none()
        
        return channel is not None
