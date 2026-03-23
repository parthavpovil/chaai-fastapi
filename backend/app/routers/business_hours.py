"""
Business Hours Router
Configure workspace operating hours and outside-hours auto-response behavior
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.models.business_hours import BusinessHours


router = APIRouter(prefix="/api/workspace/business-hours", tags=["business-hours"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BusinessHoursDayConfig(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday … 6=Sunday")
    is_closed: bool = Field(False, description="True if workspace is closed this day")
    open_time: Optional[str] = Field(None, description="Opening time HH:MM (24h), null if closed")
    close_time: Optional[str] = Field(None, description="Closing time HH:MM (24h), null if closed")
    timezone: str = Field("UTC", description="IANA timezone, e.g. America/New_York")


class BusinessHoursOut(BaseModel):
    day_of_week: int
    is_closed: bool
    open_time: Optional[str]
    close_time: Optional[str]
    timezone: str


class OutsideHoursSettings(BaseModel):
    outside_hours_message: Optional[str] = Field(None, max_length=500)
    outside_hours_behavior: Optional[str] = Field(
        None,
        description="inform_and_continue | inform_and_pause",
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _time_str(t) -> Optional[str]:
    return t.strftime("%H:%M") if t else None


def _parse_time(s: Optional[str]):
    if not s:
        return None
    from datetime import time
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time format '{s}', expected HH:MM")


def _to_out(bh: BusinessHours) -> BusinessHoursOut:
    return BusinessHoursOut(
        day_of_week=bh.day_of_week,
        is_closed=bh.is_closed,
        open_time=_time_str(bh.open_time),
        close_time=_time_str(bh.close_time),
        timezone=bh.timezone,
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[BusinessHoursOut])
async def get_business_hours(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Get the configured operating hours for the workspace (all 7 days)."""
    result = await db.execute(
        select(BusinessHours)
        .where(BusinessHours.workspace_id == current_workspace.id)
        .order_by(BusinessHours.day_of_week)
    )
    return [_to_out(bh) for bh in result.scalars().all()]


@router.put("/", response_model=List[BusinessHoursOut])
async def set_business_hours(
    request: List[BusinessHoursDayConfig],
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """
    Upsert operating hours for all days.
    Pass a list of day configs (1–7 entries, day_of_week 0–6).
    """
    if len(request) > 7:
        raise HTTPException(status_code=400, detail="Cannot configure more than 7 days")

    days_seen = [cfg.day_of_week for cfg in request]
    if len(days_seen) != len(set(days_seen)):
        raise HTTPException(status_code=400, detail="Duplicate day_of_week values in request")

    # Load existing rows into a dict keyed by day
    existing_result = await db.execute(
        select(BusinessHours)
        .where(BusinessHours.workspace_id == current_workspace.id)
    )
    existing: dict = {bh.day_of_week: bh for bh in existing_result.scalars().all()}

    updated = []
    for cfg in request:
        open_t = None if cfg.is_closed else _parse_time(cfg.open_time)
        close_t = None if cfg.is_closed else _parse_time(cfg.close_time)

        if cfg.day_of_week in existing:
            bh = existing[cfg.day_of_week]
            bh.is_closed = cfg.is_closed
            bh.open_time = open_t
            bh.close_time = close_t
            bh.timezone = cfg.timezone
        else:
            bh = BusinessHours(
                workspace_id=current_workspace.id,
                day_of_week=cfg.day_of_week,
                is_closed=cfg.is_closed,
                open_time=open_t,
                close_time=close_t,
                timezone=cfg.timezone,
            )
            db.add(bh)
        updated.append(bh)

    await db.commit()
    for bh in updated:
        await db.refresh(bh)
    return [_to_out(bh) for bh in sorted(updated, key=lambda x: x.day_of_week)]


@router.put("/outside-hours-settings", response_model=dict)
async def update_outside_hours_settings(
    request: OutsideHoursSettings,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Update the outside-hours auto-reply message and behavior."""
    valid_behaviors = {"inform_and_continue", "inform_and_pause"}
    if request.outside_hours_behavior and request.outside_hours_behavior not in valid_behaviors:
        raise HTTPException(
            status_code=400,
            detail=f"outside_hours_behavior must be one of: {', '.join(valid_behaviors)}"
        )

    if request.outside_hours_message is not None:
        current_workspace.outside_hours_message = request.outside_hours_message
    if request.outside_hours_behavior is not None:
        current_workspace.outside_hours_behavior = request.outside_hours_behavior

    await db.commit()
    return {
        "outside_hours_message": current_workspace.outside_hours_message,
        "outside_hours_behavior": current_workspace.outside_hours_behavior,
    }
