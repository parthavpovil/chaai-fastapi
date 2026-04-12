"""
Customer WebSocket Router
Real-time push endpoint for the webchat widget.
Auth: widget_id + session_token (no JWT — customers are anonymous).
The widget connects here to receive server-pushed events instead of polling.
"""
import json
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.database import get_db
from app.services.websocket_manager import customer_websocket_manager

router = APIRouter()


@router.websocket("/ws/webchat/{workspace_id}")
async def webchat_websocket_endpoint(
    websocket: WebSocket,
    workspace_id: str,
    widget_id: str = Query(..., description="Widget ID for the webchat channel"),
    session_token: str = Query(..., description="Customer session token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Customer-facing WebSocket endpoint.

    The widget connects here on panel open to receive pushed events:
      - new_message      (AI reply or human-agent reply)
      - conversation_status_changed  (escalated / agent / resolved)
      - csat_prompt      (after conversation resolved)

    The widget still sends messages via POST /api/webchat/send (HTTP).
    Only incoming message type accepted: {"type": "ping"}.
    """
    connection = None
    try:
        connection = await customer_websocket_manager.connect(
            websocket, widget_id, session_token, db
        )
        if not connection:
            return  # already closed with error code inside connect()

        # Message loop — receive-only; only ping is accepted from the customer
        while True:
            try:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await connection.send_message({"type": "error", "message": "Invalid JSON"})
                    continue

                msg_type = message.get("type")
                if msg_type == "ping":
                    await customer_websocket_manager.handle_ping(connection.connection_id)
                else:
                    await connection.send_message({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

            except WebSocketDisconnect:
                break
            except Exception:
                break

    except Exception:
        pass
    finally:
        if connection:
            await customer_websocket_manager.disconnect(connection.connection_id)


# ─── Background Cleanup Task ──────────────────────────────────────────────────

async def cleanup_stale_customer_connections():
    """
    Background task: remove customer WS connections idle > 10 minutes.
    Started in main.py lifespan, runs every 5 minutes.
    """
    while True:
        try:
            count = await customer_websocket_manager.cleanup_stale_customer_connections(
                max_idle_minutes=10
            )
            if count > 0:
                logger.info(f"Cleaned up {count} stale customer WebSocket connections")
        except Exception as e:
            logger.error(f"Customer WS cleanup error: {e}", exc_info=True)
        await asyncio.sleep(300)
