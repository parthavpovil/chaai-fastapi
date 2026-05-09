"""
Razorpay Billing Service
Subscriptions, cancellation, and webhook event handling
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


def _get_client():
    """Return a configured Razorpay client, raising a clear error if not installed."""
    try:
        import razorpay
    except ImportError:
        raise RuntimeError("razorpay package not installed. Run: pip install razorpay")

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set")

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    client.enable_retry(True)
    return client


def _plan_to_tier_map() -> dict:
    return {
        settings.RAZORPAY_PLAN_STARTER: "starter",
        settings.RAZORPAY_PLAN_GROWTH: "growth",
        settings.RAZORPAY_PLAN_PRO: "pro",
    }


async def get_or_create_razorpay_customer(db: AsyncSession, workspace: Workspace) -> str:
    """Return existing Razorpay customer ID or create a new one."""
    if workspace.razorpay_customer_id:
        return workspace.razorpay_customer_id

    client = _get_client()

    from app.models.user import User
    result = await db.execute(select(User).where(User.id == workspace.owner_id))
    owner = result.scalar_one_or_none()

    customer = client.customer.create({
        "name": owner.name if owner and hasattr(owner, "name") else workspace.name,
        "email": owner.email if owner else None,
        "notes": {
            "workspace_id": str(workspace.id),
            "workspace_slug": workspace.slug,
        }
    })
    workspace.razorpay_customer_id = customer["id"]
    await db.commit()
    return customer["id"]


async def create_subscription(
    db: AsyncSession,
    workspace: Workspace,
    tier: str,
) -> str:
    """Create a Razorpay Subscription and return the hosted checkout short_url."""
    plan_map = {
        "starter": settings.RAZORPAY_PLAN_STARTER,
        "growth": settings.RAZORPAY_PLAN_GROWTH,
        "pro": settings.RAZORPAY_PLAN_PRO,
    }
    plan_id = plan_map.get(tier)
    if not plan_id:
        raise ValueError(f"Unknown tier: {tier}")

    client = _get_client()
    customer_id = await get_or_create_razorpay_customer(db, workspace)

    subscription = client.subscription.create({
        "plan_id": plan_id,
        "customer_notify": 1,
        "total_count": 0,  # 0 = unlimited billing cycles
        "notes": {
            "workspace_id": str(workspace.id),
            "tier": tier,
        }
    })

    # Save subscription ID optimistically; tier will be confirmed via webhook
    workspace.razorpay_subscription_id = subscription["id"]
    await db.commit()

    return subscription["short_url"]


async def cancel_subscription(db: AsyncSession, workspace: Workspace) -> None:
    """Cancel the active Razorpay subscription at the end of the current billing cycle."""
    if not workspace.razorpay_subscription_id:
        raise ValueError("No active subscription to cancel")

    client = _get_client()
    client.subscription.cancel(
        workspace.razorpay_subscription_id,
        {"cancel_at_cycle_end": 1}
    )

    workspace.razorpay_subscription_id = None
    await db.commit()
    logger.info(f"Workspace {workspace.id} subscription cancelled at cycle end")


def verify_webhook_signature(body: str, signature: str) -> bool:
    """Verify Razorpay webhook signature using HMAC SHA256."""
    try:
        client = _get_client()
        client.utility.verify_webhook_signature(
            body, signature, settings.RAZORPAY_WEBHOOK_SECRET
        )
        return True
    except Exception:
        return False


async def handle_subscription_activated(event_data: dict, db: AsyncSession) -> None:
    """Handle subscription.activated — set workspace tier from plan_id."""
    subscription = event_data.get("subscription", {})
    sub_id = subscription.get("id")
    plan_id = subscription.get("plan_id")

    result = await db.execute(
        select(Workspace).where(Workspace.razorpay_subscription_id == sub_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        logger.warning(f"No workspace found for Razorpay subscription {sub_id}")
        return

    tier = _plan_to_tier_map().get(plan_id)
    if tier:
        workspace.tier = tier
        await db.commit()
        from app.services.workspace_cache import invalidate_workspace_cache
        await invalidate_workspace_cache(str(workspace.id))
        logger.info(f"Workspace {workspace.id} activated on tier {tier}")
    else:
        logger.warning(f"Unknown plan_id {plan_id} in subscription.activated")


async def handle_subscription_cancelled(event_data: dict, db: AsyncSession) -> None:
    """Handle subscription.cancelled / subscription.halted / subscription.completed — downgrade to free."""
    subscription = event_data.get("subscription", {})
    sub_id = subscription.get("id")

    result = await db.execute(
        select(Workspace).where(Workspace.razorpay_subscription_id == sub_id)
    )
    workspace = result.scalar_one_or_none()
    if workspace:
        workspace.tier = "free"
        workspace.razorpay_subscription_id = None
        await db.commit()
        from app.services.workspace_cache import invalidate_workspace_cache
        await invalidate_workspace_cache(str(workspace.id))
        logger.info(f"Workspace {workspace.id} downgraded to free")
