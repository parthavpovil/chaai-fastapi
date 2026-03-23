"""
Broadcast Tasks — arq worker for sending WhatsApp broadcasts
Run the worker with: arq app.tasks.broadcast_tasks.WorkerSettings
"""
import asyncio
from arq import create_pool
from arq.connections import RedisSettings
from app.config import settings


async def send_broadcast_job(ctx, broadcast_id: str, workspace_id: str):
    """
    arq worker job — sends one broadcast.
    Runs in the arq worker process, has its own DB session.
    """
    from app.database import AsyncSessionLocal
    from app.services.broadcast_service import execute_broadcast

    async with AsyncSessionLocal() as db:
        await execute_broadcast(db, broadcast_id, workspace_id)


class WorkerSettings:
    """arq worker configuration"""
    functions = [send_broadcast_job]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 3600  # 1 hour max per broadcast


async def enqueue_broadcast(broadcast_id: str, workspace_id: str, run_at=None):
    """Enqueue a broadcast job. run_at is a datetime for scheduled sends."""
    pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    await pool.enqueue_job(
        "send_broadcast_job",
        broadcast_id=broadcast_id,
        workspace_id=workspace_id,
        _defer_until=run_at,  # None = run immediately
    )
    await pool.aclose()
