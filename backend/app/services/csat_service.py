"""
CSAT Service
Generates signed tokens and broadcasts rating prompts for resolved conversations
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings

CSAT_TOKEN_EXPIRE_HOURS = 72
CSAT_TOKEN_TYPE = "csat"


def create_csat_token(conversation_id: str, workspace_id: str) -> str:
    """Create a signed JWT CSAT token valid for 72 hours."""
    payload = {
        "sub": conversation_id,
        "workspace_id": workspace_id,
        "type": CSAT_TOKEN_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(hours=CSAT_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_csat_token(token: str) -> Optional[dict]:
    """
    Decode and validate a CSAT token.
    Returns the payload dict if valid, None if invalid or expired.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != CSAT_TOKEN_TYPE:
            return None
        return payload
    except JWTError:
        return None


async def generate_and_send_csat_prompt(
    db: AsyncSession,
    conversation_id: str,
    workspace_id: str,
) -> None:
    """
    Generate a CSAT token and broadcast a csat_prompt WebSocket event
    to the webchat session for the given conversation.
    """
    token = create_csat_token(conversation_id, workspace_id)

    try:
        from app.services.websocket_manager import websocket_manager
        await websocket_manager.broadcast_to_workspace(
            workspace_id=workspace_id,
            message={
                "type": "csat_prompt",
                "conversation_id": conversation_id,
                "token": token,
                "expires_in_hours": CSAT_TOKEN_EXPIRE_HOURS,
            }
        )
    except Exception:
        pass  # WebSocket broadcast failure is non-fatal
