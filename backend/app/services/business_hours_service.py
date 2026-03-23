"""
Business Hours Service
Checks if the current time falls within workspace configured operating hours
"""
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.business_hours import BusinessHours
from app.models.workspace import Workspace


async def is_within_business_hours(
    workspace_id: str,
    db: AsyncSession,
) -> Tuple[bool, Optional[str]]:
    """
    Check if current wall-clock time falls within workspace operating hours.

    Returns:
        (True, None)           — within hours OR no hours configured (always open)
        (False, outside_msg)   — outside hours; outside_msg is the configured auto-reply

    Notes:
        - If no rows are configured the workspace is treated as always open.
        - Timezone is read from the first configured row (all rows share one timezone per workspace).
        - Python 3.9+ zoneinfo is used; requires the 'tzdata' package on non-Linux platforms.
    """
    result = await db.execute(
        select(BusinessHours)
        .where(BusinessHours.workspace_id == UUID(workspace_id))
    )
    rows = result.scalars().all()

    if not rows:
        return True, None  # not configured → always open

    tz_name = rows[0].timezone or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    now_local = datetime.now(tz)
    today_dow = now_local.weekday()  # 0=Monday matches our schema

    today_config = next((r for r in rows if r.day_of_week == today_dow), None)

    if today_config is None or today_config.is_closed:
        outside_msg = await _get_outside_message(workspace_id, db)
        return False, outside_msg

    current_time = now_local.time()
    if today_config.open_time is None or today_config.close_time is None:
        return True, None  # misconfigured row → treat as open

    within = today_config.open_time <= current_time <= today_config.close_time
    if not within:
        outside_msg = await _get_outside_message(workspace_id, db)
        return False, outside_msg

    return True, None


async def get_outside_hours_behavior(workspace_id: str, db: AsyncSession) -> str:
    """Return 'inform_and_continue' or 'inform_and_pause' (default: inform_and_continue)."""
    result = await db.execute(
        select(Workspace.outside_hours_behavior).where(Workspace.id == UUID(workspace_id))
    )
    behavior = result.scalar_one_or_none()
    return behavior or "inform_and_continue"


async def _get_outside_message(workspace_id: str, db: AsyncSession) -> Optional[str]:
    result = await db.execute(
        select(Workspace.outside_hours_message).where(Workspace.id == UUID(workspace_id))
    )
    msg = result.scalar_one_or_none()
    return msg or "We're currently outside our business hours. We'll get back to you as soon as possible."
