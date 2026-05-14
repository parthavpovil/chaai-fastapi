"""
Scheduled jobs that run on the arq worker via cron_jobs.

These were previously embedded in the Gunicorn web workers (via a Redis
leader-election loop in main.py). Moving them here:
  - Frees the web worker event loop to handle only HTTP / WebSocket I/O.
  - Eliminates the leader-election complexity — arq's `unique=True` cron
    locks already guarantee exactly-once execution across worker instances.
  - Lets each task run with the arq worker's own memory budget and event
    loop, isolated from WebSocket traffic.

Each function below is a thin wrapper around existing service logic.
"""
import logging

from app.database import AsyncSessionLocal
from app.services.alerting_service import AlertingService
from app.services.email_service import EmailService
from app.services.metrics_service import MetricsService
from app.tasks.agent_status_tasks import _mark_stale_agents_offline
from app.tasks.reconciliation import _reconcile

logger = logging.getLogger(__name__)


async def run_agent_status_check(ctx) -> None:
    """Mark agents with stale heartbeats as offline. Runs every 1 minute."""
    try:
        await _mark_stale_agents_offline()
    except Exception as e:
        logger.error("run_agent_status_check failed: %s", e, exc_info=True)


async def run_reconciliation_sweep(ctx) -> None:
    """Re-enqueue orphaned webchat messages. Runs every 1 minute."""
    try:
        await _reconcile()
    except Exception as e:
        logger.error("run_reconciliation_sweep failed: %s", e, exc_info=True)


async def run_metrics_collection(ctx) -> None:
    """Refresh cached system metrics. Runs every 1 minute."""
    try:
        async with AsyncSessionLocal() as db:
            await MetricsService(db).get_system_metrics()
    except Exception as e:
        logger.error("run_metrics_collection failed: %s", e, exc_info=True)


async def run_health_check(ctx) -> None:
    """System health check + alert generation. Runs every 5 minutes."""
    try:
        async with AsyncSessionLocal() as db:
            email_service = EmailService()
            await AlertingService(db, email_service).check_system_health()
    except Exception as e:
        logger.error("run_health_check failed: %s", e, exc_info=True)
