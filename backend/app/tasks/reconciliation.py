"""
Reconciliation sweeper — re-enqueues orphaned webchat messages.

Runs every 60 seconds, finds customer messages older than 60 s that have
no assistant reply in their conversation, and calls enqueue_message_job.
Because enqueue_message_job uses _job_id=msg:<message_id>, re-enqueuing a
message whose job is already queued/running is a silent no-op (arq deduplicates).
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL = 60       # seconds between sweeps
_MESSAGE_AGE_THRESHOLD = 60  # only consider messages older than this

_task: asyncio.Task = None

_ORPHAN_QUERY = text("""
    SELECT
        m.id            AS id,
        m.conversation_id,
        c.workspace_id,
        ct.external_id  AS session_token,
        ct.channel_id
    FROM messages m
    JOIN conversations c  ON c.id  = m.conversation_id
    JOIN contacts     ct ON ct.id = c.contact_id
    WHERE m.role = 'customer'
      AND m.created_at < :cutoff
      AND c.channel_type = 'webchat'
      AND NOT EXISTS (
          SELECT 1
          FROM messages am
          WHERE am.conversation_id = c.id
            AND am.role = 'assistant'
      )
    LIMIT 50
""")


async def start_reconciliation_sweeper() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_sweep_loop())
    logger.info("Reconciliation sweeper started")


async def stop_reconciliation_sweeper() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    logger.info("Reconciliation sweeper stopped")


async def _sweep_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL)
            await _reconcile()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Reconciliation sweep error: %s", e, exc_info=True)


async def _reconcile() -> None:
    from app.tasks.message_tasks import enqueue_message_job

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_MESSAGE_AGE_THRESHOLD)

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(_ORPHAN_QUERY, {"cutoff": cutoff})
            rows = result.fetchall()
        except Exception as e:
            logger.error("Reconciliation query failed: %s", e, exc_info=True)
            return

        if not rows:
            return

        logger.info("Reconciliation: re-enqueueing %d orphaned messages", len(rows))
        for row in rows:
            try:
                await enqueue_message_job(
                    message_id=str(row.id),
                    conversation_id=str(row.conversation_id),
                    workspace_id=str(row.workspace_id),
                    session_token=row.session_token or "",
                    channel_id=str(row.channel_id),
                )
            except Exception as e:
                logger.warning(
                    "Reconciliation: failed to enqueue message %s: %s", row.id, e
                )
