"""
CSAT Service
Generates signed tokens and broadcasts rating prompts for resolved conversations
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from jose import jwt, JWTError
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
    conversation_id: str,
    workspace_id: str,
) -> None:
    """
    Generate a CSAT token and push a csat_prompt event to the customer's
    WS session for the given conversation.

    Opens its own session so it can safely run as a safe_create_task background
    task — never hold a reference to a request-scoped session across a task boundary.
    """
    from app.database import AsyncSessionLocal
    from app.models.contact import Contact
    from app.models.conversation import Conversation
    from app.services.websocket_events import notify_customer_csat_prompt
    from uuid import UUID as _UUID

    token = create_csat_token(conversation_id, workspace_id)

    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(Contact.external_id)
            .join(Conversation, Conversation.contact_id == Contact.id)
            .where(Conversation.id == _UUID(conversation_id))
        )
        session_token = row.scalar_one_or_none()
        if session_token:
            await notify_customer_csat_prompt(workspace_id, session_token, token)
