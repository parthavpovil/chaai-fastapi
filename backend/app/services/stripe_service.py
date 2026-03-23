"""
Stripe Billing Service
Checkout, customer portal, and subscription event handling
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

# Map Stripe price IDs to our tier names
PRICE_TO_TIER = {}


def _get_stripe():
    """Return stripe module, raising a clear error if not installed."""
    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe
    except ImportError:
        raise RuntimeError("stripe package not installed. Run: pip install stripe")


def _price_to_tier_map() -> dict:
    return {
        settings.STRIPE_PRICE_STARTER: "starter",
        settings.STRIPE_PRICE_GROWTH: "growth",
        settings.STRIPE_PRICE_PRO: "pro",
    }


async def get_or_create_stripe_customer(db: AsyncSession, workspace: Workspace) -> str:
    """Return existing Stripe customer ID or create a new one."""
    if workspace.stripe_customer_id:
        return workspace.stripe_customer_id

    stripe = _get_stripe()
    # Load workspace owner's email
    from app.models.user import User
    result = await db.execute(select(User).where(User.id == workspace.owner_id))
    owner = result.scalar_one_or_none()

    customer = stripe.Customer.create(
        email=owner.email if owner else None,
        metadata={"workspace_id": str(workspace.id), "workspace_slug": workspace.slug}
    )
    workspace.stripe_customer_id = customer["id"]
    await db.commit()
    return customer["id"]


async def create_checkout_session(
    db: AsyncSession,
    workspace: Workspace,
    tier: str,
    success_url: str,
    cancel_url: str
) -> str:
    """Create a Stripe Checkout session and return the URL."""
    price_map = {
        "starter": settings.STRIPE_PRICE_STARTER,
        "growth": settings.STRIPE_PRICE_GROWTH,
        "pro": settings.STRIPE_PRICE_PRO,
    }
    price_id = price_map.get(tier)
    if not price_id:
        raise ValueError(f"Unknown tier: {tier}")

    stripe = _get_stripe()
    customer_id = await get_or_create_stripe_customer(db, workspace)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"workspace_id": str(workspace.id), "tier": tier}
    )
    return session["url"]


async def create_customer_portal_session(
    db: AsyncSession,
    workspace: Workspace,
    return_url: str
) -> str:
    """Create a Stripe Customer Portal session URL."""
    stripe = _get_stripe()
    customer_id = await get_or_create_stripe_customer(db, workspace)

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url
    )
    return session["url"]


async def handle_subscription_updated(event_data: dict, db: AsyncSession) -> None:
    """Handle customer.subscription.updated webhook event."""
    subscription = event_data.get("object", {})
    customer_id = subscription.get("customer")
    status = subscription.get("status")

    result = await db.execute(
        select(Workspace).where(Workspace.stripe_customer_id == customer_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        logger.warning(f"No workspace found for Stripe customer {customer_id}")
        return

    workspace.stripe_subscription_id = subscription.get("id")

    if status == "active":
        # Determine tier from price
        items = subscription.get("items", {}).get("data", [])
        price_id = items[0]["price"]["id"] if items else None
        tier = _price_to_tier_map().get(price_id)
        if tier:
            workspace.tier = tier
            logger.info(f"Workspace {workspace.id} upgraded to {tier}")

    elif status in ("canceled", "unpaid", "past_due"):
        workspace.tier = "free"
        logger.info(f"Workspace {workspace.id} downgraded to free (subscription {status})")

    await db.commit()


async def handle_subscription_deleted(event_data: dict, db: AsyncSession) -> None:
    """Handle customer.subscription.deleted webhook event."""
    subscription = event_data.get("object", {})
    customer_id = subscription.get("customer")

    result = await db.execute(
        select(Workspace).where(Workspace.stripe_customer_id == customer_id)
    )
    workspace = result.scalar_one_or_none()
    if workspace:
        workspace.tier = "free"
        workspace.stripe_subscription_id = None
        await db.commit()
        logger.info(f"Workspace {workspace.id} downgraded to free (subscription deleted)")
