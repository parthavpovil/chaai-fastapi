"""
Billing Router
Stripe checkout, portal, and status endpoints
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.config import settings


router = APIRouter(prefix="/api/billing", tags=["billing"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier: str = Field(..., pattern="^(starter|growth|pro)$")
    success_url: str = Field(default="")
    cancel_url: str = Field(default="")


class BillingStatusResponse(BaseModel):
    tier: str
    stripe_customer_id: Optional[str]
    stripe_subscription_id: Optional[str]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/checkout")
async def create_checkout(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe Checkout session to upgrade the workspace tier."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured")

    from app.services.stripe_service import create_checkout_session

    success = request.success_url or f"{settings.APP_URL}/billing/success"
    cancel = request.cancel_url or f"{settings.APP_URL}/billing/cancel"

    try:
        url = await create_checkout_session(
            db=db,
            workspace=current_workspace,
            tier=request.tier,
            success_url=success,
            cancel_url=cancel
        )
        return {"checkout_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create checkout session: {e}")


@router.post("/portal")
async def create_portal(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe Customer Portal session for subscription management."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured")

    from app.services.stripe_service import create_customer_portal_session

    return_url = f"{settings.APP_URL}/billing"

    try:
        url = await create_customer_portal_session(
            db=db, workspace=current_workspace, return_url=return_url
        )
        return {"portal_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create portal session: {e}")


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """Get current billing/tier status."""
    return BillingStatusResponse(
        tier=current_workspace.tier or "free",
        stripe_customer_id=current_workspace.stripe_customer_id,
        stripe_subscription_id=current_workspace.stripe_subscription_id,
    )


# ─── Stripe webhook (in webhooks.py for /webhooks/stripe) ─────────────────────
# The actual POST /webhooks/stripe route is added to app/routers/webhooks.py below.
# This module only handles the owner-facing billing management endpoints.
