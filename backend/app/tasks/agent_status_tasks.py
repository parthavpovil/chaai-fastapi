"""
Agent Status Background Task
Marks agents as offline when their heartbeat expires (> 5 minutes old)
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_task: asyncio.Task = None
HEARTBEAT_TIMEOUT_MINUTES = 5
CHECK_INTERVAL_SECONDS = 60


async def _run_agent_status_check() -> None:
    """Periodically set agents with stale heartbeats to offline."""
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            await _mark_stale_agents_offline()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Agent status check error: {e}")


async def _mark_stale_agents_offline() -> None:
    from sqlalchemy import select, update
    from app.database import get_db
    from app.models.agent import Agent

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)

    async for db in get_db():
        try:
            await db.execute(
                update(Agent)
                .where(Agent.status == "online")
                .where(Agent.last_heartbeat_at < cutoff)
                .values(status="offline")
            )
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to mark stale agents offline: {e}")
            await db.rollback()
        break


async def start_agent_status_tasks() -> None:
    global _task
    _task = asyncio.create_task(_run_agent_status_check())
    logger.info("Agent status background task started")


async def stop_agent_status_tasks() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    logger.info("Agent status background task stopped")
