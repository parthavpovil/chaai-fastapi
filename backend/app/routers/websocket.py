"""
WebSocket Router
Handles WebSocket connections with JWT authentication and message routing
"""
import json
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

logger = logging.getLogger(__name__)
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.services.websocket_manager import websocket_manager, WebSocketConnection
from app.services.websocket_events import WebSocketEventBroadcaster


router = APIRouter()


@router.websocket("/ws/{workspace_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    workspace_id: str,
    token: str = Query(..., description="JWT authentication token"),
    db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint for real-time communication
    
    Args:
        websocket: WebSocket connection
        workspace_id: Workspace ID from URL path
        token: JWT token from query parameter
        db: Database session
    
    Authentication:
        - JWT token must be provided in query parameter
        - Token must contain valid user_id and workspace_id
        - workspace_id in URL must match token workspace_id
    
    Message Format:
        Incoming messages should be JSON with 'type' field:
        - {"type": "ping"} - Keep-alive ping
        - {"type": "subscribe", "events": ["escalation", "new_message"]} - Event subscription
        - {"type": "get_stats"} - Request workspace statistics
    
    Outgoing message types:
        - connection_established - Connection confirmation
        - ping/pong - Keep-alive messages
        - escalation - New escalation events
        - agent_claim - Agent claiming conversations
        - new_message - New messages in conversations
        - conversation_status_change - Status updates
        - system_notification - System notifications
    """
    connection: Optional[WebSocketConnection] = None
    
    try:
        # Establish connection with authentication
        connection = await websocket_manager.connect(websocket, token, db)
        
        if not connection:
            # Connection failed (authentication error)
            return
        
        # Verify workspace_id matches token
        if connection.workspace_id != workspace_id:
            await websocket.close(code=4003, reason="Workspace ID mismatch")
            return
        
        # Connection established successfully
        logger.info(f"WebSocket connection established: {connection.connection_id}")
        
        # Message handling loop
        while True:
            try:
                # Wait for incoming message
                data = await websocket.receive_text()
                
                # Parse message
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await connection.send_message({
                        "type": "error",
                        "message": "Invalid JSON format"
                    })
                    continue
                
                # Handle message based on type
                await handle_websocket_message(connection, message, db)
                
            except WebSocketDisconnect:
                logger.info(f"WebSocket client disconnected: {connection.connection_id}")
                break
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}", exc_info=True)
                sent = await connection.send_message({
                    "type": "error",
                    "message": "Message processing error"
                })
                if not sent:
                    break
    
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}", exc_info=True)

    finally:
        # Clean up connection
        if connection:
            await websocket_manager.disconnect(connection.connection_id)


async def handle_websocket_message(
    connection: WebSocketConnection,
    message: dict,
    db: AsyncSession
):
    """
    Handle incoming WebSocket message
    
    Args:
        connection: WebSocket connection
        message: Parsed message data
        db: Database session
    """
    message_type = message.get("type")
    
    if message_type == "ping":
        # Handle ping - update last ping time and send pong
        await websocket_manager.handle_ping(connection.connection_id)
    
    elif message_type == "subscribe":
        # Handle event subscription
        events = message.get("events", [])
        await handle_event_subscription(connection, events)
    
    elif message_type == "get_stats":
        # Handle statistics request
        await handle_stats_request(connection, db)
    
    elif message_type == "get_conversations":
        # Handle conversation list request
        await handle_conversations_request(connection, message, db)
    
    elif message_type == "get_agents":
        # Handle agents list request
        await handle_agents_request(connection, db)
    
    else:
        # Unknown message type
        await connection.send_message({
            "type": "error",
            "message": f"Unknown message type: {message_type}"
        })


async def handle_event_subscription(
    connection: WebSocketConnection,
    events: list
):
    """
    Handle event subscription request
    
    Args:
        connection: WebSocket connection
        events: List of event types to subscribe to
    """
    # For now, all connections receive all events
    # In the future, this could be used for selective event filtering
    
    valid_events = [
        "escalation", "agent_claim", "new_message", 
        "conversation_status_change", "agent_status_change",
        "document_processing", "system_notification"
    ]
    
    subscribed_events = [event for event in events if event in valid_events]
    
    await connection.send_message({
        "type": "subscription_confirmed",
        "subscribed_events": subscribed_events,
        "available_events": valid_events
    })


async def handle_stats_request(
    connection: WebSocketConnection,
    db: AsyncSession
):
    """
    Handle workspace statistics request
    
    Args:
        connection: WebSocket connection
        db: Database session
    """
    try:
        from app.services.conversation_manager import ConversationManager
        
        # Get conversation statistics
        conversation_manager = ConversationManager(db)
        conversation_stats = await conversation_manager.get_conversation_statistics(
            connection.workspace_id
        )
        
        # Get WebSocket connection stats
        ws_connections = await websocket_manager.get_workspace_connections(
            connection.workspace_id
        )
        
        stats = {
            "conversations": conversation_stats,
            "websocket_connections": len(ws_connections),
            "connected_users": [
                {
                    "user_email": conn["user_email"],
                    "connected_at": conn["connected_at"]
                }
                for conn in ws_connections
            ]
        }
        
        await connection.send_message({
            "type": "workspace_stats",
            "stats": stats
        })
        
    except Exception as e:
        await connection.send_message({
            "type": "error",
            "message": f"Failed to get statistics: {str(e)}"
        })


async def handle_conversations_request(
    connection: WebSocketConnection,
    message: dict,
    db: AsyncSession
):
    """
    Handle conversations list request
    
    Args:
        connection: WebSocket connection
        message: Request message with optional filters
        db: Database session
    """
    try:
        from app.services.conversation_manager import ConversationManager
        
        # Parse request parameters
        status = message.get("status")  # Optional status filter
        limit = min(message.get("limit", 20), 100)  # Max 100 conversations
        offset = message.get("offset", 0)
        
        conversation_manager = ConversationManager(db)
        conversations = await conversation_manager.get_workspace_conversations(
            workspace_id=connection.workspace_id,
            status=status,
            limit=limit,
            offset=offset
        )
        
        # Format conversation data for WebSocket response
        conversation_data = []
        for conv in conversations:
            conversation_data.append({
                "conversation_id": conv.id,
                "status": conv.status,
                "contact_name": conv.contact.name if conv.contact else "Unknown",
                "channel_type": conv.channel_type,
                "agent_name": conv.assigned_agent.name if conv.assigned_agent else None,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat()
            })
        
        await connection.send_message({
            "type": "conversations_list",
            "conversations": conversation_data,
            "total_count": len(conversation_data),
            "filters": {
                "status": status,
                "limit": limit,
                "offset": offset
            }
        })
        
    except Exception as e:
        await connection.send_message({
            "type": "error",
            "message": f"Failed to get conversations: {str(e)}"
        })


async def handle_agents_request(
    connection: WebSocketConnection,
    db: AsyncSession
):
    """
    Handle agents list request
    
    Args:
        connection: WebSocket connection
        db: Database session
    """
    try:
        from sqlalchemy import select
        from app.models.agent import Agent
        
        # Get workspace agents
        result = await db.execute(
            select(Agent)
            .where(Agent.workspace_id == connection.workspace_id)
            .order_by(Agent.created_at)
        )
        agents = result.scalars().all()
        
        # Format agent data
        agent_data = []
        for agent in agents:
            agent_data.append({
                "agent_id": agent.id,
                "name": agent.name,
                "email": agent.email,
                "is_active": agent.is_active,
                "created_at": agent.created_at.isoformat()
            })
        
        await connection.send_message({
            "type": "agents_list",
            "agents": agent_data,
            "total_count": len(agent_data)
        })
        
    except Exception as e:
        await connection.send_message({
            "type": "error",
            "message": f"Failed to get agents: {str(e)}"
        })


# ─── WebSocket Health Check Endpoint ──────────────────────────────────────────

@router.get("/ws/health")
async def websocket_health():
    """
    WebSocket service health check
    
    Returns:
        WebSocket manager statistics and health status
    """
    stats = websocket_manager.get_stats()
    
    return {
        "status": "healthy",
        "websocket_stats": stats,
        "timestamp": stats["timestamp"]
    }


# ─── WebSocket Management Endpoints ───────────────────────────────────────────

@router.get("/ws/connections/{workspace_id}")
async def get_workspace_connections(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get WebSocket connections for a workspace
    
    Args:
        workspace_id: Workspace ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of active connections for the workspace
    
    Raises:
        HTTPException: If workspace access denied
    """
    # Verify workspace access
    if str(current_workspace.id) != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to workspace denied"
        )
    connections = await websocket_manager.get_workspace_connections(workspace_id)
    
    return {
        "workspace_id": workspace_id,
        "connections": connections,
        "connection_count": len(connections)
    }


@router.post("/ws/broadcast/{workspace_id}")
async def broadcast_message(
    workspace_id: str,
    message: dict,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Broadcast message to all connections in a workspace
    
    Args:
        workspace_id: Workspace ID
        message: Message to broadcast
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Broadcast result with connection count
    
    Raises:
        HTTPException: If workspace access denied
    """
    # Verify workspace access
    if str(current_workspace.id) != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to workspace denied"
        )
    sent_count = await websocket_manager.broadcast_to_workspace(workspace_id, message)
    
    return {
        "workspace_id": workspace_id,
        "message_sent_to": sent_count,
        "broadcast_successful": sent_count > 0
    }


# ─── Background Task for Connection Cleanup ──────────────────────────────────

async def cleanup_stale_connections():
    """
    Background task to clean up stale WebSocket connections
    Should be run periodically (e.g., every 5 minutes)
    """
    while True:
        try:
            cleanup_count = await websocket_manager.cleanup_stale_connections(max_idle_minutes=30)
            if cleanup_count > 0:
                logger.info(f"Cleaned up {cleanup_count} stale WebSocket connections")
        except Exception as e:
            logger.error(f"Error during WebSocket cleanup: {e}", exc_info=True)
        
        # Wait 5 minutes before next cleanup
        await asyncio.sleep(300)