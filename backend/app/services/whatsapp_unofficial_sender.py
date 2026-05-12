"""
Unofficial WhatsApp Message Sender
Sends replies back to customers via the Baileys-based WhatsApp gateway.
"""
import logging

import httpx

logger = logging.getLogger(__name__)


async def send_whatsapp_unofficial_message(
    gateway_url: str,
    api_key: str,
    tenant_id: str,
    recipient_phone: str,
    text: str,
) -> bool:
    """
    Send a text message to a WhatsApp user via the unofficial gateway.

    Args:
        gateway_url: Base URL of the Baileys gateway (e.g. http://localhost:3000)
        api_key: Gateway API key (X-Gateway-Token)
        tenant_id: Tenant identifier registered on the gateway
        recipient_phone: Recipient phone number without JID suffix (e.g. "919876543210")
        text: Message text to send

    Returns:
        True if sent successfully, False otherwise
    """
    url = f"{gateway_url.rstrip('/')}/messages/send"
    payload = {
        "tenantId": tenant_id,
        "jid": f"{recipient_phone}@s.whatsapp.net",
        "text": text,
    }
    headers = {
        "X-Gateway-Token": api_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code not in (200, 201):
                logger.error(
                    "Unofficial WhatsApp sendMessage failed: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return False
            data = response.json()
            if data.get("error"):
                logger.error("Unofficial WhatsApp gateway error: %s", data["error"])
                return False
            return True
    except Exception:
        logger.exception(
            "Unofficial WhatsApp sendMessage raised an exception for tenant=%s recipient=%s",
            tenant_id,
            recipient_phone,
        )
        return False
