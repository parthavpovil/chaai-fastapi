"""
Telegram Message Sender
Sends replies back to customers via the Telegram Bot API.
"""
import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


async def send_telegram_message(bot_token: str, chat_id: str | int, text: str) -> bool:
    """
    Send a text message to a Telegram chat.

    Args:
        bot_token: Decrypted Telegram bot token
        chat_id: Telegram chat ID to send the message to
        text: Message text to send

    Returns:
        True if sent successfully, False otherwise
    """
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            if response.status_code != 200:
                logger.error(
                    "Telegram sendMessage failed: status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return False
            result = response.json()
            if not result.get("ok"):
                logger.error("Telegram sendMessage error: %s", result.get("description"))
                return False
            return True
    except Exception:
        logger.exception("Telegram sendMessage raised an exception for chat_id=%s", chat_id)
        return False
