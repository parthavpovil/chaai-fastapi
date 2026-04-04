"""
Billing Router
Razorpay subscription checkout, cancellation, and status endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.config import settings


router = APIRouter(
    prefix="/api/billing",
    tags=["billing"],
    dependencies=[Depends(require_permission("billing.manage"))],
)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier: str = Field(..., pattern="^(starter|growth|pro)$")


class BillingStatusResponse(BaseModel):
    tier: str
    razorpay_customer_id: Optional[str]
    razorpay_subscription_id: Optional[str]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/checkout")
async def create_checkout(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create a Razorpay Subscription and return the hosted checkout URL."""
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Billing not configured")

    from app.services.razorpay_service import create_subscription

    try:
        url = await create_subscription(
            db=db,
            workspace=current_workspace,
            tier=request.tier,
        )
        return {"checkout_url": url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create subscription: {e}")


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Cancel the active Razorpay subscription at end of current billing cycle."""
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Billing not configured")

    from app.services.razorpay_service import cancel_subscription as _cancel

    try:
        await _cancel(db=db, workspace=current_workspace)
        return {"status": "cancelled"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {e}")


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """Get current billing/tier status."""
    return BillingStatusResponse(
        tier=current_workspace.tier or "free",
        razorpay_customer_id=current_workspace.razorpay_customer_id,
        razorpay_subscription_id=current_workspace.razorpay_subscription_id,
    )


# ─── Razorpay webhook (in webhooks.py for /webhooks/razorpay) ─────────────────
# The actual POST /webhooks/razorpay route is in app/routers/webhooks.py.
# This module only handles the owner-facing billing management endpoints.
