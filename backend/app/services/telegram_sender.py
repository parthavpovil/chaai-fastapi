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

    async def _post_message(client: httpx.AsyncClient, payload: dict) -> tuple[bool, str]:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return False, response.text
        result = response.json()
        if not result.get("ok"):
            return False, str(result.get("description", "Unknown Telegram API error"))
        return True, ""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            primary_payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            sent, error = await _post_message(client, primary_payload)
            if sent:
                return True

            # AI output can include markdown-like text or symbols that break Telegram HTML parsing.
            # Retry once without parse_mode to maximize delivery reliability.
            fallback_payload = {
                "chat_id": chat_id,
                "text": text,
            }
            fallback_sent, fallback_error = await _post_message(client, fallback_payload)
            if fallback_sent:
                logger.warning(
                    "Telegram sendMessage succeeded only after plain-text fallback for chat_id=%s. Initial error=%s",
                    chat_id,
                    error,
                )
                return True

            logger.error(
                "Telegram sendMessage failed after fallback for chat_id=%s. Initial error=%s Fallback error=%s",
                chat_id,
                error,
                fallback_error,
            )
            return False
    except Exception:
        logger.exception("Telegram sendMessage raised an exception for chat_id=%s", chat_id)
        return False
