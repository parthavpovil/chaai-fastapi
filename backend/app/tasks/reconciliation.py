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

from sqlalchemy import select, exists

from app.database import AsyncSessionLocal
from app.models.message import Message
from app.models.conversation import Conversation
from app.models.contact import Contact

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL = 60       # seconds between sweeps
_MESSAGE_AGE_THRESHOLD = 60  # only consider messages older than this

_task: asyncio.Task = None


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
            # Find webchat customer messages older than threshold with no assistant
            # reply in the same conversation created after them.
            reply_exists = (
                select(Message.id)
                .where(Message.conversation_id == Message.conversation_id)
                .where(Message.role == "assistant")
                .where(Message.created_at > Message.created_at)
                .correlate(Message)
                .exists()
            )

            # Subquery: assistant message in same conversation after customer message
            customer_msg = Message.__table__.alias("cm")
            assistant_reply = Message.__table__.alias("ar")

            from sqlalchemy import and_, not_
            stmt = (
                select(
                    Message.id,
                    Message.conversation_id,
                    Conversation.workspace_id,
                    Contact.external_id.label("session_token"),
                    Conversation.channel_id,
                )
                .join(Conversation, Conversation.id == Message.conversation_id)
                .join(Contact, Contact.id == Conversation.contact_id)
                .where(Message.role == "customer")
                .where(Message.created_at < cutoff)
                .where(Conversation.channel_type == "webchat")
                .where(
                    not_(
                        exists(
                            select(Message.id)
                            .where(Message.conversation_id == Conversation.id)
                            .where(Message.role == "assistant")
                        )
                    )
                )
                .limit(50)  # cap each sweep to avoid thundering herd
            )

            result = await db.execute(stmt)
            rows = result.fetchall()

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
        except Exception as e:
            logger.error("Reconciliation query failed: %s", e, exc_info=True)
