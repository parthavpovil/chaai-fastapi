"""
WhatsApp Template Service
Submits templates to Meta for approval and syncs status back
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.whatsapp_template import WhatsAppTemplate
from app.models.channel import Channel


async def submit_template_to_meta(
    db: AsyncSession,
    template: WhatsAppTemplate,
    workspace_id: str,
) -> WhatsAppTemplate:
    """
    Submit a template to Meta for review via the Graph API.
    Updates template status to 'pending' and stores meta_template_id.
    """
    access_token, waba_id = await _get_waba_credentials(db, workspace_id)
    if not access_token or not waba_id:
        raise ValueError("WhatsApp channel missing access_token or waba_id")

    components = _build_template_components(template)

    payload = {
        "name": template.name,
        "category": template.category,
        "language": template.language,
        "components": components,
    }

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v17.0/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

    template.meta_template_id = data.get("id")
    template.status = "pending"
    template.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(template)
    return template


async def sync_template_statuses(db: AsyncSession, workspace_id: str) -> None:
    """
    Sync template approval status from Meta.
    Called by the background task loop in main.py lifespan.
    """
    access_token, waba_id = await _get_waba_credentials(db, workspace_id)
    if not access_token or not waba_id:
        return

    result = await db.execute(
        select(WhatsAppTemplate)
        .where(WhatsAppTemplate.workspace_id == workspace_id)
        .where(WhatsAppTemplate.status == "pending")
        .where(WhatsAppTemplate.meta_template_id.isnot(None))
    )
    pending_templates = result.scalars().all()
    if not pending_templates:
        return

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://graph.facebook.com/v17.0/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id,name,status,quality_score,rejected_reason"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return
        data = resp.json().get("data", [])

    meta_by_id = {t["id"]: t for t in data}

    for template in pending_templates:
        meta = meta_by_id.get(template.meta_template_id)
        if not meta:
            continue

        new_status = meta.get("status", "").lower()
        if new_status in ("approved", "rejected"):
            template.status = new_status
            if new_status == "approved":
                template.approved_at = datetime.now(timezone.utc)
            elif new_status == "rejected":
                template.rejection_reason = meta.get("rejected_reason", "")

    await db.commit()


async def start_template_sync_loop(workspace_id: str) -> None:
    """
    Background loop that syncs template statuses every hour.
    Register via asyncio.create_task() in main.py lifespan.
    """
    from app.database import AsyncSessionLocal

    while True:
        try:
            async with AsyncSessionLocal() as db:
                await sync_template_statuses(db, workspace_id)
        except Exception:
            pass
        await asyncio.sleep(3600)


def _build_template_components(template: WhatsAppTemplate) -> list:
    """Build the components array for the Meta template submission API."""
    components = []

    if template.header_type and template.header_type != "none":
        header = {"type": "HEADER", "format": template.header_type.upper()}
        if template.header_type == "text":
            header["text"] = template.header_content or ""
        components.append(header)

    components.append({"type": "BODY", "text": template.body})

    if template.footer:
        components.append({"type": "FOOTER", "text": template.footer})

    if template.buttons:
        components.append({"type": "BUTTONS", "buttons": template.buttons})

    return components


async def _get_waba_credentials(db: AsyncSession, workspace_id: str):
    """Get decrypted access_token and waba_id from the workspace's WhatsApp channel."""
    result = await db.execute(
        select(Channel)
        .where(Channel.workspace_id == workspace_id)
        .where(Channel.type == "whatsapp")
        .where(Channel.is_active == True)
    )
    channel = result.scalar_one_or_none()
    if not channel or not channel.config:
        return None, None

    try:
        from app.services.encryption import decrypt_credential
        access_token = decrypt_credential(channel.config.get("access_token", ""))
        waba_id = decrypt_credential(channel.config.get("waba_id", ""))
        return access_token, waba_id
    except Exception:
        return None, None
