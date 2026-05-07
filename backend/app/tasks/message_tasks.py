"""
Message Processing Worker (arq)

Runs the AI pipeline (routing, RAG, escalation, agent) for webchat messages
off the HTTP hot path.  Start with:
    arq app.tasks.message_tasks.MessageWorkerSettings
"""
import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis
from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)

# Per-tier max concurrent jobs per workspace
_TIER_CONCURRENCY = {
    "free":    2,
    "starter": 3,
    "growth":  5,
    "pro":    10,
}
_DEFAULT_CONCURRENCY = 2
_SEMAPHORE_TTL = 300   # seconds — prevents leaked slots on worker crash

# Lua script: atomic check-and-increment
_ACQUIRE_LUA = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return 1
"""

# Module-level arq pool — created once, reused across requests
_pool = None
_pool_lock = asyncio.Lock()


async def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            from arq import create_pool
            _pool = await create_pool(RedisSettings.from_dsn(settings.redis_queue_url))
    return _pool


async def enqueue_message_job(
    *,
    message_id: str,
    conversation_id: str,
    workspace_id: str,
    session_token: str,
    channel_id: str,
) -> None:
    """Enqueue a webchat message for async AI processing.

    Uses _job_id=msg:<message_id> so arq silently drops duplicate enqueues
    (e.g. from the reconciliation sweeper when the job is still running).
    """
    pool = await _get_pool()
    job = await pool.enqueue_job(
        "process_message_job",
        message_id=message_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        session_token=session_token,
        channel_id=channel_id,
        _job_id=f"msg:{message_id}",
    )
    if job is None:
        logger.info("[enqueue] msg:%s already queued/running — skipped (dedup)", message_id)
    else:
        logger.info("[enqueue] msg:%s enqueued to Redis queue (job_id=%s)", message_id, job.job_id)


# ── Semaphore helpers ─────────────────────────────────────────────────────────

async def _acquire_semaphore(redis_client: aioredis.Redis, workspace_id: str, limit: int) -> bool:
    key = f"ws_concurrency:{workspace_id}"
    result = await redis_client.eval(_ACQUIRE_LUA, 1, key, limit, _SEMAPHORE_TTL)
    return bool(result)


async def _release_semaphore(redis_client: aioredis.Redis, workspace_id: str) -> None:
    key = f"ws_concurrency:{workspace_id}"
    try:
        val = await redis_client.get(key)
        if val is not None and int(val) > 0:
            await redis_client.decr(key)
    except Exception as e:
        logger.warning("Failed to release semaphore for workspace %s: %s", workspace_id, e)


# ── Job function ──────────────────────────────────────────────────────────────

async def process_message_job(
    ctx,
    *,
    message_id: str,
    conversation_id: str,
    workspace_id: str,
    session_token: str,
    channel_id: str,
) -> None:
    """arq job: run the full AI pipeline for one webchat message."""
    from arq import ArqRedis
    from arq.worker import Retry
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.message import Message
    from app.models.workspace import Workspace
    from app.models.channel import Channel
    from app.services.message_processor import MessageProcessor
    from app.services.escalation_router import check_and_escalate_message
    from app.services.rag_engine import generate_rag_response
    from app.services.websocket_events import notify_new_message, notify_customer_new_message

    logger.info("[worker] picked up msg:%s conversation=%s workspace=%s",
                message_id, conversation_id, workspace_id)

    redis_client: aioredis.Redis = aioredis.from_url(
        settings.redis_queue_url, decode_responses=True
    )

    try:
        async with AsyncSessionLocal() as db:
            # ── 1. Idempotency ────────────────────────────────────────────────
            # Find the customer message to get its created_at timestamp
            msg_result = await db.execute(
                select(Message).where(Message.id == message_id)
            )
            customer_msg = msg_result.scalar_one_or_none()
            if customer_msg is None:
                logger.warning("process_message_job: message %s not found, skipping", message_id)
                return

            # Check if an assistant reply already exists after this message
            reply_result = await db.execute(
                select(Message.id)
                .where(Message.conversation_id == conversation_id)
                .where(Message.role == "assistant")
                .where(Message.created_at > customer_msg.created_at)
            )
            if reply_result.scalar_one_or_none() is not None:
                logger.info(
                    "process_message_job: reply already exists for message %s, skipping", message_id
                )
                return

            # ── 2. Load workspace + channel ───────────────────────────────────
            ws_result = await db.execute(
                select(Workspace).where(Workspace.id == workspace_id)
            )
            workspace = ws_result.scalar_one_or_none()
            if workspace is None:
                logger.error("process_message_job: workspace %s not found", workspace_id)
                return  # permanent failure — don't retry

            ch_result = await db.execute(
                select(Channel).where(Channel.id == channel_id)
            )
            channel = ch_result.scalar_one_or_none()
            if channel is None:
                logger.error("process_message_job: channel %s not found", channel_id)
                return

            # ── 3. Per-workspace concurrency semaphore ────────────────────────
            tier = getattr(workspace, "tier", "free") or "free"
            limit = _TIER_CONCURRENCY.get(tier, _DEFAULT_CONCURRENCY)
            acquired = await _acquire_semaphore(redis_client, workspace_id, limit)
            if not acquired:
                logger.info(
                    "process_message_job: concurrency limit (%d) hit for workspace %s, retrying",
                    limit, workspace_id,
                )
                raise Retry(defer=5)

            try:
                # ── 4. Run routing logic ──────────────────────────────────────
                meta          = (workspace.meta or {})
                ai_mode       = meta.get("ai_mode", "rag")
                ai_enabled    = workspace.ai_enabled if workspace is not None else True
                auto_esc      = workspace.auto_escalation_enabled if workspace is not None else True
                agents        = workspace.agents_enabled if workspace is not None else False

                message_content = customer_msg.content or "[User sent a file]"
                processor = MessageProcessor(db)

                # Branch 1: AI disabled + human agents → direct routing
                if not ai_enabled and agents:
                    try:
                        from app.services.escalation_router import EscalationRouter
                        esc_result = await EscalationRouter(db).process_escalation(
                            conversation_id=conversation_id,
                            workspace_id=workspace_id,
                            escalation_reason="direct_routing",
                            classification_data={
                                "should_escalate": True,
                                "confidence": 1.0,
                                "reason": "direct_routing",
                                "category": "routing_mode",
                                "classification_method": "workspace_config",
                            },
                            priority="medium",
                        )
                        ack_msg_id = esc_result.get("acknowledgment_message_id")
                        if ack_msg_id:
                            await notify_customer_new_message(
                                db=db,
                                workspace_id=workspace_id,
                                session_token=session_token,
                                message_id=str(ack_msg_id),
                            )
                    except Exception as e:
                        logger.error(
                            "process_message_job: direct routing escalation failed for %s: %s",
                            conversation_id, e,
                        )

                # Branch 2: AI disabled, no agents → silent receive
                elif not ai_enabled:
                    pass

                else:
                    # Branch 3: AI enabled
                    handled = False

                    if ai_mode == "ai_agent":
                        try:
                            from app.services.ai_agent_runner import ai_agent_runner
                            agent_result = await ai_agent_runner.run(
                                db=db,
                                conversation_id=conversation_id,
                                new_message=message_content,
                                workspace_id=workspace_id,
                                channel_id=channel_id,
                            )
                            if agent_result.handled:
                                handled = True
                                ai_msg = await processor.create_message(
                                    conversation_id=conversation_id,
                                    content=agent_result.reply,
                                    role="assistant",
                                    channel_type="webchat",
                                    metadata={"ai_agent": True, "escalated": agent_result.escalated},
                                )
                                await notify_new_message(
                                    db=db,
                                    workspace_id=workspace_id,
                                    conversation_id=conversation_id,
                                    message_id=str(ai_msg.id),
                                )
                                await notify_customer_new_message(
                                    db=db,
                                    workspace_id=workspace_id,
                                    session_token=session_token,
                                    message_id=str(ai_msg.id),
                                )
                        except Exception as e:
                            logger.error(
                                "process_message_job: AI agent runner error for %s: %s",
                                conversation_id, e,
                            )

                    if not handled:
                        escalation_result = None
                        if auto_esc:
                            escalation_result = await check_and_escalate_message(
                                db=db,
                                conversation_id=conversation_id,
                                workspace_id=workspace_id,
                                message_content=message_content,
                            )

                        if not escalation_result:
                            try:
                                logger.info(
                                    "process_message_job RAG call — workspace=%s conversation=%s query=%r",
                                    workspace_id, conversation_id, message_content[:80],
                                )
                                rag_result = await generate_rag_response(
                                    db=db,
                                    workspace_id=workspace_id,
                                    query=message_content,
                                    conversation_id=conversation_id,
                                    max_tokens=300,
                                )

                                rag_escalated = False
                                if rag_result.get("used_fallback"):
                                    logger.warning(
                                        "process_message_job RAG fallback — workspace=%s chunks=%d",
                                        workspace_id, rag_result.get("relevant_chunks_count", 0),
                                    )
                                    if auto_esc:
                                        try:
                                            from app.services.escalation_router import EscalationRouter
                                            fallback_esc = await EscalationRouter(db).process_escalation(
                                                conversation_id=conversation_id,
                                                workspace_id=workspace_id,
                                                escalation_reason="implicit",
                                                classification_data={
                                                    "should_escalate": True,
                                                    "confidence": 1.0,
                                                    "reason": "RAG knowledge base could not answer the query",
                                                    "category": "complex",
                                                    "classification_method": "rag_fallback",
                                                },
                                                priority="medium",
                                            )
                                            if fallback_esc:
                                                rag_escalated = True
                                                ack_msg_id = fallback_esc.get("acknowledgment_message_id")
                                                if ack_msg_id:
                                                    await notify_customer_new_message(
                                                        db=db,
                                                        workspace_id=workspace_id,
                                                        session_token=session_token,
                                                        message_id=str(ack_msg_id),
                                                    )
                                        except Exception as esc_err:
                                            logger.error(
                                                "process_message_job: RAG-fallback escalation failed: %s",
                                                esc_err,
                                            )
                                else:
                                    logger.info(
                                        "process_message_job RAG success — workspace=%s chunks=%d",
                                        workspace_id, rag_result.get("relevant_chunks_count", 0),
                                    )

                                if not rag_escalated:
                                    ai_message = await processor.create_message(
                                        conversation_id=conversation_id,
                                        content=rag_result["response"],
                                        role="assistant",
                                        channel_type="webchat",
                                        metadata={
                                            "rag_used": True,
                                            "input_tokens": rag_result["input_tokens"],
                                            "output_tokens": rag_result["output_tokens"],
                                            "webchat_response": True,
                                        },
                                    )
                                    if ai_message:
                                        await notify_new_message(
                                            db=db,
                                            workspace_id=workspace_id,
                                            conversation_id=conversation_id,
                                            message_id=str(ai_message.id),
                                        )
                                        await notify_customer_new_message(
                                            db=db,
                                            workspace_id=workspace_id,
                                            session_token=session_token,
                                            message_id=str(ai_message.id),
                                        )

                            except Exception as e:
                                # Transient — let arq retry
                                logger.error(
                                    "process_message_job: RAG failed for %s: %s",
                                    conversation_id, e, exc_info=True,
                                )
                                raise

            finally:
                await _release_semaphore(redis_client, workspace_id)

    finally:
        await redis_client.aclose()


# ── arq WorkerSettings ────────────────────────────────────────────────────────

class MessageWorkerSettings:
    """Run with: arq app.tasks.message_tasks.MessageWorkerSettings"""
    functions = [process_message_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_queue_url)
    max_jobs = 20
    job_timeout = 120      # 2-minute hard cap per job
    max_tries = 4          # 4 attempts total (1 original + 3 retries)
    keep_result = 3600     # keep result 1h for deduplication
