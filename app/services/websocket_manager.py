"""
WebSocket Manager Service
Handles real-time WebSocket connections with workspace isolation and JWT authentication
"""
import json
import asyncio
from typing import Dict, Set, List, Optional, Any
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import AuthService
from app.models.user import User
from app.models.workspace import Workspace


class WebSocketConnectionError(Exception):
    """Base exception for WebSocket connection errors"""
    pass


class WebSocketConnection:
    """
    Represents a single WebSocket connection with metadata
    """
    
    def __init__(
        self,
        websocket: WebSocket,
        connection_id: str,
        workspace_id: str,
        user_id: str,
        user_email: str,
        user_role: str = "owner"
    ):
        self.websocket = websocket
        self.connection_id = connection_id
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.user_email = user_email
        self.user_role = user_role
        self.connected_at = datetime.now(timezone.utc)
        self.last_ping = datetime.now(timezone.utc)
    
    async def send_message(self, message: Dict[str, Any]) -> bool:
        """
        Send message to WebSocket connection
        
        Args:
            message: Message data to send
        
        Returns:
            True if sent successfully, False if connection closed
        """
        try:
            await self.websocket.send_text(json.dumps(message))
            return True
        except Exception as e:
            print(f"Failed to send WebSocket message to {self.connection_id}: {e}")
            return False
    
    async def send_ping(self) -> bool:
        """
        Send ping to keep connection alive
        
        Returns:
            True if ping sent successfully
        """
        try:
            ping_message = {
                "type": "ping",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return await self.send_message(ping_message)
        except Exception:
            return False
    
    def update_last_ping(self):
        """Update last ping timestamp"""
        self.last_ping = datetime.now(timezone.utc)


class WebSocketManager:
    """
    WebSocket manager with workspace-isolated connection pools
    Handles authentication, connection lifecycle, and message broadcasting
    """
    
    def __init__(self):
        # Workspace-isolated connection pools
        # Format: {workspace_id: {connection_id: WebSocketConnection}}
        self.workspace_connections: Dict[str, Dict[str, WebSocketConnection]] = {}
        
        # Connection lookup by connection ID
        # Format: {connection_id: WebSocketConnection}
        self.connections: Dict[str, WebSocketConnection] = {}
        
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
    
    def generate_connection_id(self, workspace_id: str, user_id: str) -> str:
        """
        Generate unique connection ID
        
        Args:
            workspace_id: Workspace ID
            user_id: User ID
        
        Returns:
            Unique connection ID
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return f"{workspace_id}_{user_id}_{timestamp}"
    
    async def authenticate_connection(
        self,
        token: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Authenticate WebSocket connection using JWT token
        
        Args:
            token: JWT token
            db: Database session
        
        Returns:
            User and workspace info if authenticated, None otherwise
        """
        try:
            # Verify JWT token
            payload = AuthService.decode_access_token(token)
            if not payload:
                return None
            
            user_id = payload.get("user_id")
            workspace_id = payload.get("workspace_id")
            
            if not user_id or not workspace_id:
                return None
            
            # Verify user and workspace exist
            from sqlalchemy import select
            
            result = await db.execute(
                select(User.email, Workspace.id)
                .join(Workspace, Workspace.owner_id == User.id)
                .where(User.id == user_id)
                .where(Workspace.id == workspace_id)
            )
            
            row = result.first()
            if not row:
                return None
            
            return {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "user_email": row.email,
                "user_role": "owner"  # For now, only owners can connect
            }
            
        except Exception as e:
            print(f"WebSocket authentication failed: {e}")
            return None
    
    async def connect(
        self,
        websocket: WebSocket,
        token: str,
        db: AsyncSession
    ) -> Optional[WebSocketConnection]:
        """
        Establish WebSocket connection with authentication
        
        Args:
            websocket: WebSocket instance
            token: JWT authentication token
            db: Database session
        
        Returns:
            WebSocketConnection if successful, None if authentication failed
        """
        try:
            # Authenticate connection
            auth_info = await self.authenticate_connection(token, db)
            if not auth_info:
                await websocket.close(code=4001, reason="Authentication failed")
                return None
            
            # Accept WebSocket connection
            await websocket.accept()
            
            # Create connection object
            connection_id = self.generate_connection_id(
                auth_info["workspace_id"], 
                auth_info["user_id"]
            )
            
            connection = WebSocketConnection(
                websocket=websocket,
                connection_id=connection_id,
                workspace_id=auth_info["workspace_id"],
                user_id=auth_info["user_id"],
                user_email=auth_info["user_email"],
                user_role=auth_info["user_role"]
            )
            
            # Add to connection pools
            async with self._lock:
                workspace_id = connection.workspace_id
                
                if workspace_id not in self.workspace_connections:
                    self.workspace_connections[workspace_id] = {}
                
                self.workspace_connections[workspace_id][connection_id] = connection
                self.connections[connection_id] = connection
            
            # Send connection confirmation
            await connection.send_message({
                "type": "connection_established",
                "connection_id": connection_id,
                "workspace_id": workspace_id,
                "connected_at": connection.connected_at.isoformat()
            })
            
            print(f"WebSocket connected: {connection_id} for workspace {workspace_id}")
            return connection
            
        except Exception as e:
            print(f"WebSocket connection failed: {e}")
            try:
                await websocket.close(code=4000, reason="Connection failed")
            except:
                pass
            return None
    
    async def disconnect(self, connection_id: str) -> bool:
        """
        Disconnect and cleanup WebSocket connection
        
        Args:
            connection_id: Connection ID to disconnect
        
        Returns:
            True if disconnected successfully
        """
        async with self._lock:
            connection = self.connections.get(connection_id)
            if not connection:
                return False
            
            workspace_id = connection.workspace_id
            
            # Remove from connection pools
            if workspace_id in self.workspace_connections:
                self.workspace_connections[workspace_id].pop(connection_id, None)
                
                # Clean up empty workspace pools
                if not self.workspace_connections[workspace_id]:
                    del self.workspace_connections[workspace_id]
            
            self.connections.pop(connection_id, None)
            
            # Close WebSocket if still open
            try:
                await connection.websocket.close()
            except:
                pass
            
            print(f"WebSocket disconnected: {connection_id}")
            return True
    
    async def broadcast_to_workspace(
        self,
        workspace_id: str,
        message: Dict[str, Any],
        exclude_connection_id: Optional[str] = None
    ) -> int:
        """
        Broadcast message to all connections in a workspace
        
        Args:
            workspace_id: Workspace ID
            message: Message to broadcast
            exclude_connection_id: Optional connection ID to exclude
        
        Returns:
            Number of connections that received the message
        """
        if workspace_id not in self.workspace_connections:
            return 0
        
        connections = self.workspace_connections[workspace_id].copy()
        sent_count = 0
        failed_connections = []
        
        for connection_id, connection in connections.items():
            if connection_id == exclude_connection_id:
                continue
            
            success = await connection.send_message(message)
            if success:
                sent_count += 1
            else:
                failed_connections.append(connection_id)
        
        # Clean up failed connections
        for failed_id in failed_connections:
            await self.disconnect(failed_id)
        
        return sent_count
    
    async def send_to_connection(
        self,
        connection_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        Send message to specific connection
        
        Args:
            connection_id: Target connection ID
            message: Message to send
        
        Returns:
            True if sent successfully
        """
        connection = self.connections.get(connection_id)
        if not connection:
            return False
        
        success = await connection.send_message(message)
        if not success:
            await self.disconnect(connection_id)
        
        return success
    
    async def get_workspace_connections(self, workspace_id: str) -> List[Dict[str, Any]]:
        """
        Get information about connections in a workspace
        
        Args:
            workspace_id: Workspace ID
        
        Returns:
            List of connection information
        """
        if workspace_id not in self.workspace_connections:
            return []
        
        connections_info = []
        for connection in self.workspace_connections[workspace_id].values():
            connections_info.append({
                "connection_id": connection.connection_id,
                "user_id": connection.user_id,
                "user_email": connection.user_email,
                "user_role": connection.user_role,
                "connected_at": connection.connected_at.isoformat(),
                "last_ping": connection.last_ping.isoformat()
            })
        
        return connections_info
    
    async def cleanup_stale_connections(self, max_idle_minutes: int = 30) -> int:
        """
        Clean up stale connections that haven't pinged recently
        
        Args:
            max_idle_minutes: Maximum idle time in minutes
        
        Returns:
            Number of connections cleaned up
        """
        from datetime import timedelta
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_idle_minutes)
        stale_connections = []
        
        for connection_id, connection in self.connections.items():
            if connection.last_ping < cutoff_time:
                stale_connections.append(connection_id)
        
        cleanup_count = 0
        for connection_id in stale_connections:
            if await self.disconnect(connection_id):
                cleanup_count += 1
        
        return cleanup_count
    
    async def handle_ping(self, connection_id: str) -> bool:
        """
        Handle ping from connection
        
        Args:
            connection_id: Connection ID that sent ping
        
        Returns:
            True if ping handled successfully
        """
        connection = self.connections.get(connection_id)
        if not connection:
            return False
        
        connection.update_last_ping()
        
        # Send pong response
        pong_message = {
            "type": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return await connection.send_message(pong_message)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get WebSocket manager statistics
        
        Returns:
            Statistics about connections
        """
        total_connections = len(self.connections)
        workspace_counts = {
            workspace_id: len(connections)
            for workspace_id, connections in self.workspace_connections.items()
        }
        
        return {
            "total_connections": total_connections,
            "workspace_count": len(self.workspace_connections),
            "workspace_connections": workspace_counts,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# ─── Global WebSocket Manager Instance ────────────────────────────────────────

websocket_manager = WebSocketManager()


# ─── Convenience Functions ────────────────────────────────────────────────────

async def broadcast_escalation_event(
    workspace_id: str,
    conversation_id: str,
    escalation_data: Dict[str, Any]
) -> int:
    """
    Broadcast escalation event to workspace connections
    
    Args:
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        escalation_data: Escalation metadata
    
    Returns:
        Number of connections notified
    """
    message = {
        "type": "escalation",
        "conversation_id": conversation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **escalation_data
    }
    
    return await websocket_manager.broadcast_to_workspace(workspace_id, message)


async def broadcast_agent_claim_event(
    workspace_id: str,
    conversation_id: str,
    agent_id: str,
    agent_name: str
) -> int:
    """
    Broadcast agent claim event to workspace connections
    
    Args:
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        agent_id: Agent ID
        agent_name: Agent name
    
    Returns:
        Number of connections notified
    """
    message = {
        "type": "agent_claim",
        "conversation_id": conversation_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return await websocket_manager.broadcast_to_workspace(workspace_id, message)


async def broadcast_new_message_event(
    workspace_id: str,
    conversation_id: str,
    message_data: Dict[str, Any]
) -> int:
    """
    Broadcast new message event to workspace connections
    
    Args:
        workspace_id: Workspace ID
        conversation_id: Conversation ID
        message_data: Message metadata
    
    Returns:
        Number of connections notified
    """
    message = {
        "type": "new_message",
        "conversation_id": conversation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **message_data
    }
    
    return await websocket_manager.broadcast_to_workspace(workspace_id, message)