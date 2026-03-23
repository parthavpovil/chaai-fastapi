"""
Broadcast Service
Resolves audience, sends template messages, tracks per-recipient delivery
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.whatsapp_template import WhatsAppTemplate
from app.models.contact import Contact
from app.models.channel import Channel


OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "opt out", "remove me"}


async def execute_broadcast(db: AsyncSession, broadcast_id: str, workspace_id: str):
    """
    Main broadcast execution function called by the arq worker.
    Sends template messages to all resolved contacts at ~80 msg/sec.
    """
    broadcast = await _get_broadcast(db, broadcast_id, workspace_id)
    if not broadcast or broadcast.status == "cancelled":
        return

    contacts = await resolve_audience(db, broadcast)

    broadcast.status = "sending"
    broadcast.started_at = datetime.now(timezone.utc)
    broadcast.recipient_count = len(contacts)
    await db.commit()

    # Get channel credentials (first active WhatsApp channel in workspace)
    access_token, phone_number_id = await _get_channel_credentials(db, workspace_id)
    if not access_token:
        broadcast.status = "failed"
        await db.commit()
        return

    template = await db.get(WhatsAppTemplate, broadcast.template_id)
    if not template:
        broadcast.status = "failed"
        await db.commit()
        return

    for contact in contacts:
        try:
            resolved_vars = _resolve_variables(broadcast.variable_mapping or {}, contact)
            wamid = await _send_single_template_message(
                access_token=access_token,
                phone_number_id=phone_number_id,
                template=template,
                to=contact.phone,
                resolved_vars=resolved_vars,
            )
            db.add(BroadcastRecipient(
                broadcast_id=broadcast_id,
                contact_id=str(contact.id),
                phone=contact.phone,
                variable_values=resolved_vars,
                status="sent",
                whatsapp_message_id=wamid,
                sent_at=datetime.now(timezone.utc),
            ))
        except Exception as e:
            db.add(BroadcastRecipient(
                broadcast_id=broadcast_id,
                contact_id=str(contact.id),
                phone=contact.phone,
                status="failed",
                failed_reason=str(e),
            ))

        await db.commit()
        await asyncio.sleep(0.013)  # ~80 msg/sec — WhatsApp Cloud API rate limit

    broadcast.status = "sent"
    broadcast.completed_at = datetime.now(timezone.utc)
    await db.commit()


async def resolve_audience(db: AsyncSession, broadcast: Broadcast) -> list:
    """Filter contacts by audience_type. Excludes opted-out contacts without a phone."""
    query = (
        select(Contact)
        .where(Contact.workspace_id == broadcast.workspace_id)
        .where(Contact.broadcast_opted_out == False)
        .where(Contact.phone.isnot(None))
    )
    if broadcast.audience_type == "tag":
        tags = (broadcast.audience_filter or {}).get("tags", [])
        if tags:
            query = query.where(Contact.tags.overlap(tags))
    elif broadcast.audience_type == "manual":
        contact_ids = (broadcast.audience_filter or {}).get("contact_ids", [])
        if contact_ids:
            query = query.where(Contact.id.in_(contact_ids))

    result = await db.execute(query)
    return result.scalars().all()


def _resolve_variables(variable_mapping: dict, contact: Contact) -> dict:
    """
    Resolve template variable placeholders for a specific contact.
    Supports "contact.name", "contact.phone", "contact.email", "static:<value>"
    """
    resolved = {}
    for placeholder, source in variable_mapping.items():
        if source.startswith("static:"):
            resolved[placeholder] = source[len("static:"):]
        elif source == "contact.name":
            resolved[placeholder] = contact.name or ""
        elif source == "contact.phone":
            resolved[placeholder] = contact.phone or ""
        elif source == "contact.email":
            resolved[placeholder] = contact.email or ""
        else:
            resolved[placeholder] = ""
    return resolved


async def _send_single_template_message(
    access_token: str,
    phone_number_id: str,
    template: WhatsAppTemplate,
    to: str,
    resolved_vars: dict,
) -> Optional[str]:
    """Send a template message via WhatsApp Cloud API. Returns wamid on success."""
    import httpx

    components = []
    if resolved_vars:
        body_params = [
            {"type": "text", "text": v}
            for k, v in sorted(resolved_vars.items())
        ]
        if body_params:
            components.append({"type": "body", "parameters": body_params})

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template.name,
            "language": {"code": template.language},
            "components": components,
        }
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v17.0/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("messages", [])
        return messages[0].get("id") if messages else None


async def _get_broadcast(db: AsyncSession, broadcast_id: str, workspace_id: str) -> Optional[Broadcast]:
    result = await db.execute(
        select(Broadcast)
        .where(Broadcast.id == broadcast_id)
        .where(Broadcast.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


async def _get_channel_credentials(db: AsyncSession, workspace_id: str):
    """Get decrypted access_token and phone_number_id from the workspace's WhatsApp channel."""
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
        phone_number_id = decrypt_credential(channel.config.get("phone_number_id", ""))
        return access_token, phone_number_id
    except Exception:
        return None, None
