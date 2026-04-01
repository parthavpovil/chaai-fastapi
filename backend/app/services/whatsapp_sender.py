"""
WhatsApp Message Sender
Sends replies back to customers via the WhatsApp Cloud API.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

WHATSAPP_API_BASE = "https://graph.facebook.com/v17.0"


async def send_whatsapp_message(
    access_token: str,
    phone_number_id: str,
    to: str,
    text: str,
) -> bool:
    """
    Send a text message to a WhatsApp user.

    Args:
        access_token: Decrypted WhatsApp Cloud API access token
        phone_number_id: WhatsApp phone number ID
        to: Recipient phone number in E.164 format (e.g. "15551234567")
        text: Message text to send

    Returns:
        True if sent successfully, False otherwise
    """
    url = f"{WHATSAPP_API_BASE}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code not in (200, 201):
                logger.error(
                    "WhatsApp sendMessage failed: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return False
            data = response.json()
            if data.get("error"):
                logger.error("WhatsApp sendMessage API error: %s", data["error"])
                return False
            return True
    except Exception:
        logger.exception("WhatsApp sendMessage raised an exception for to=%s", to)
        return False
