"""
WebSocket Manager Service
Handles real-time WebSocket connections with workspace isolation and JWT authentication
"""
import json
import asyncio
import logging
from typing import Dict, Set, List, Optional, Any
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import AuthService
from app.models.user import User
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


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
            logger.warning(f"Failed to send WebSocket message to {self.connection_id}: {e}")
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
            logger.error(f"WebSocket authentication failed: {e}", exc_info=True)
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
            
            logger.info(f"WebSocket connected: {connection_id} for workspace {workspace_id}")
            return connection

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}", exc_info=True)
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
            
            logger.info(f"WebSocket disconnected: {connection_id}")
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


# ─── Customer WebSocket (Widget-Facing) ───────────────────────────────────────
# Completely isolated from agent connections — no JWT, no user_id.
# Identity is: workspace_id + session_token (= Contact.external_id for webchat).

class CustomerWebSocketConnection:
    """Represents a single customer (widget) WebSocket connection."""

    def __init__(
        self,
        websocket: WebSocket,
        connection_id: str,
        workspace_id: str,
        session_token: str,
    ):
        self.websocket = websocket
        self.connection_id = connection_id
        self.workspace_id = workspace_id
        self.session_token = session_token
        self.connected_at = datetime.now(timezone.utc)
        self.last_ping = datetime.now(timezone.utc)

    async def send_message(self, message: Dict[str, Any]) -> bool:
        try:
            await self.websocket.send_text(json.dumps(message))
            return True
        except Exception as e:
            logger.warning(f"Failed to send customer WS message to {self.connection_id}: {e}")
            return False

    def update_last_ping(self):
        self.last_ping = datetime.now(timezone.utc)


class CustomerWebSocketManager:
    """
    WebSocket manager for customer (widget) connections.
    Pools are keyed workspace_id → session_token → connection.
    Completely separate from WebSocketManager — no agent data is accessible here.
    """

    def __init__(self):
        # workspace_id → session_token → CustomerWebSocketConnection
        self.customer_connections: Dict[str, Dict[str, CustomerWebSocketConnection]] = {}
        # connection_id → CustomerWebSocketConnection  (fast disconnect/ping lookup)
        self.connections_by_id: Dict[str, CustomerWebSocketConnection] = {}
        self._lock = asyncio.Lock()

    async def authenticate_customer(
        self,
        widget_id: str,
        session_token: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        """
        Validate widget_id and session_token.
        Returns {"workspace_id": str, "channel_id": str} or None.
        Does NOT require an active conversation — customer can pre-connect.
        """
        try:
            from app.routers.webchat import get_webchat_channel_by_widget_id
            channel = await get_webchat_channel_by_widget_id(db, widget_id)
            if not channel:
                return None
            # session_token is only required to be non-empty (contact may not exist yet
            # on the very first message, so we don't enforce Contact lookup here)
            if not session_token:
                return None
            return {
                "workspace_id": str(channel.workspace_id),
                "channel_id": str(channel.id),
            }
        except Exception as e:
            logger.error(f"Customer WS authentication failed: {e}", exc_info=True)
            return None

    async def connect(
        self,
        websocket: WebSocket,
        widget_id: str,
        session_token: str,
        db: AsyncSession,
    ) -> Optional[CustomerWebSocketConnection]:
        """
        Authenticate, accept, and register a customer WS connection.
        If a connection for the same session_token already exists in this workspace,
        it is replaced (new tab / page refresh wins).
        """
        try:
            auth_info = await self.authenticate_customer(widget_id, session_token, db)
            if not auth_info:
                await websocket.close(code=4001, reason="Authentication failed")
                return None

            await websocket.accept()

            from uuid import uuid4
            connection_id = str(uuid4())
            workspace_id = auth_info["workspace_id"]

            connection = CustomerWebSocketConnection(
                websocket=websocket,
                connection_id=connection_id,
                workspace_id=workspace_id,
                session_token=session_token,
            )

            async with self._lock:
                if workspace_id not in self.customer_connections:
                    self.customer_connections[workspace_id] = {}

                # Replace any existing connection for this session_token
                old = self.customer_connections[workspace_id].get(session_token)
                if old:
                    self.connections_by_id.pop(old.connection_id, None)
                    try:
                        await old.websocket.close(code=1001, reason="Replaced by new connection")
                    except Exception:
                        pass

                self.customer_connections[workspace_id][session_token] = connection
                self.connections_by_id[connection_id] = connection

            await connection.send_message({
                "type": "connection_established",
                "connection_id": connection_id,
                "workspace_id": workspace_id,
                "connected_at": connection.connected_at.isoformat(),
            })

            logger.info(f"Customer WS connected: {connection_id} (workspace={workspace_id})")
            return connection

        except Exception as e:
            logger.error(f"Customer WS connection failed: {e}", exc_info=True)
            try:
                await websocket.close(code=4000, reason="Connection failed")
            except Exception:
                pass
            return None

    async def disconnect(self, connection_id: str) -> bool:
        """Remove connection from both pools and close the WebSocket."""
        async with self._lock:
            connection = self.connections_by_id.get(connection_id)
            if not connection:
                return False

            workspace_id = connection.workspace_id
            session_token = connection.session_token

            # Only remove from workspace pool if it's still THIS connection
            # (could have been replaced by a newer connection for the same session)
            ws_pool = self.customer_connections.get(workspace_id, {})
            if ws_pool.get(session_token) is connection:
                ws_pool.pop(session_token, None)
                if not ws_pool:
                    self.customer_connections.pop(workspace_id, None)

            self.connections_by_id.pop(connection_id, None)

            try:
                await connection.websocket.close()
            except Exception:
                pass

            logger.info(f"Customer WS disconnected: {connection_id}")
            return True

    async def send_to_session(
        self,
        workspace_id: str,
        session_token: str,
        message: Dict[str, Any],
    ) -> bool:
        """
        Push a message to the customer identified by session_token.
        Returns True if sent, False if no active connection (silent — never raises).
        """
        try:
            ws_pool = self.customer_connections.get(workspace_id, {})
            connection = ws_pool.get(session_token)
            if not connection:
                return False

            success = await connection.send_message(message)
            if not success:
                await self.disconnect(connection.connection_id)
            return success
        except Exception as e:
            logger.error(f"customer send_to_session error: {e}", exc_info=True)
            return False

    async def handle_ping(self, connection_id: str) -> bool:
        """Update last_ping and send pong."""
        connection = self.connections_by_id.get(connection_id)
        if not connection:
            return False
        connection.update_last_ping()
        return await connection.send_message({
            "type": "pong",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def cleanup_stale_customer_connections(self, max_idle_minutes: int = 10) -> int:
        """Remove connections idle longer than max_idle_minutes (default 10)."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_idle_minutes)
        stale = [
            conn.connection_id
            for conn in list(self.connections_by_id.values())
            if conn.last_ping < cutoff
        ]
        count = 0
        for cid in stale:
            if await self.disconnect(cid):
                count += 1
        return count


# ─── Global Customer WebSocket Manager Instance ───────────────────────────────

customer_websocket_manager = CustomerWebSocketManager()