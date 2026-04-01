"""
Instagram DM Sender
Sends replies back to customers via the Meta Graph API (Messenger Platform).
"""
import logging

import httpx

logger = logging.getLogger(__name__)

META_GRAPH_API_BASE = "https://graph.facebook.com/v17.0"


async def send_instagram_message(
    access_token: str,
    page_id: str,
    recipient_id: str,
    text: str,
) -> bool:
    """
    Send a text message to an Instagram DM thread.

    Args:
        access_token: Decrypted Meta page access token
        page_id: Instagram-connected Facebook page ID
        recipient_id: Instagram-scoped user ID of the recipient
        text: Message text to send

    Returns:
        True if sent successfully, False otherwise
    """
    url = f"{META_GRAPH_API_BASE}/{page_id}/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
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
                    "Instagram sendMessage failed: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return False
            data = response.json()
            if data.get("error"):
                logger.error("Instagram sendMessage API error: %s", data["error"])
                return False
            return True
    except Exception:
        logger.exception(
            "Instagram sendMessage raised an exception for recipient_id=%s", recipient_id
        )
        return False
