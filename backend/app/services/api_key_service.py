"""
API Key Service
Generate, validate, and manage programmatic access keys
"""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.api_key import APIKey
from app.models.workspace import Workspace


KEY_PREFIX = "csk_"
KEY_LENGTH = 32  # 32 bytes = 64 hex chars


def generate_api_key() -> Tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (raw_key, prefix, key_hash).
    raw_key is shown to the user once and never stored.
    """
    raw = KEY_PREFIX + secrets.token_hex(KEY_LENGTH)
    prefix = raw[:12]  # "csk_" + first 8 hex chars
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, key_hash


async def validate_api_key(
    raw_key: str,
    db: AsyncSession
) -> Optional[Tuple[APIKey, Workspace]]:
    """
    Validate a raw API key. Returns (APIKey, Workspace) or None.
    Updates last_used_at on success.
    """
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        return None

    if not api_key.is_active:
        return None

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        return None

    # Load workspace
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == api_key.workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        return None

    # Update last_used_at (fire and forget style — don't fail auth if this fails)
    try:
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        await db.rollback()

    return api_key, workspace
