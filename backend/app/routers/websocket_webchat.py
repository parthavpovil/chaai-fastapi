"""
Customer WebSocket Router
Real-time push endpoint for the webchat widget.
Auth: widget_id + session_token (no JWT — customers are anonymous).
The widget connects here to receive server-pushed events instead of polling.
"""
import json
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

_AUTH_TIMEOUT = 10.0  # seconds

logger = logging.getLogger(__name__)

from app.database import AsyncSessionLocal
from app.services.websocket_manager import customer_websocket_manager

router = APIRouter()


@router.websocket("/ws/webchat/{workspace_id}")
async def webchat_websocket_endpoint(
    websocket: WebSocket,
    workspace_id: str,
    widget_id: str = Query(..., description="Widget ID for the webchat channel"),
):
    """
    Customer-facing WebSocket endpoint.

    The widget connects here on panel open. Auth via first message:
      {"type": "auth", "session_token": "<token>"}
    session_token is NOT in the URL — proxies log URLs, and session tokens
    must not appear in access logs.

    widget_id stays in the query string — it is a public identifier embedded
    in the widget JS and contains no secret.

    Pushed event types:
      - new_message, conversation_status_changed, csat_prompt

    The widget sends messages via POST /api/webchat/send (HTTP).
    Only {"type": "ping"} is accepted after auth.
    """
    connection = None
    try:
        await websocket.accept()

        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=_AUTH_TIMEOUT)
            auth_msg = json.loads(raw)
        except asyncio.TimeoutError:
            await websocket.close(code=4001, reason="Authentication timeout")
            return
        except (json.JSONDecodeError, WebSocketDisconnect):
            await websocket.close(code=4001, reason="Invalid auth message")
            return

        session_token = auth_msg.get("session_token") if auth_msg.get("type") == "auth" else None
        if not session_token:
            await websocket.close(code=4001, reason="Expected {type:auth, session_token:...}")
            return

        # Use a short-lived DB session JUST for the auth lookup. Using
        # `db: AsyncSession = Depends(get_db)` on a WebSocket endpoint keeps the
        # session (and an "idle in transaction" Postgres connection) open for
        # the entire WS lifetime — with 4 gunicorn workers × many customers, the
        # pool gets exhausted, request handlers block waiting for connections,
        # and gunicorn's heartbeat times out → SIGKILL.
        async with AsyncSessionLocal() as db:
            connection = await customer_websocket_manager.connect(
                websocket, widget_id, session_token, db, already_accepted=True
            )
        if not connection:
            return

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
