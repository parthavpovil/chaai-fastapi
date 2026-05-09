"""
Task helpers — safe fire-and-forget async tasks with error logging.
"""
import asyncio
import logging
from typing import Coroutine, Any

logger = logging.getLogger(__name__)


def safe_create_task(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    """
    Schedule a coroutine as a background task and log any unhandled exception.

    Unlike bare asyncio.create_task(), errors inside the coroutine are not
    silently dropped — they are logged at ERROR level so they appear in
    structured logs and alert on-call.

    The coroutine MUST NOT hold a reference to a request-scoped AsyncSession.
    Open a fresh session inside the coroutine instead.
    """
    async def _wrapper() -> None:
        try:
            await coro
        except Exception:
            label = name or getattr(coro, "__qualname__", repr(coro))
            logger.error("Background task %r raised an unhandled exception", label, exc_info=True)

    return asyncio.create_task(_wrapper(), name=name)
