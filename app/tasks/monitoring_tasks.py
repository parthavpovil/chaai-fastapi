"""
Monitoring Background Tasks

Periodic health checks and alerting tasks
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
import os

from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_async_session
from app.services.alerting_service import AlertingService
from app.services.email_service import EmailService
from app.services.metrics_service import MetricsService

logger = logging.getLogger(__name__)

class MonitoringTaskManager:
    """Manages background monitoring tasks"""
    
    def __init__(self):
        self.running = False
        self.tasks = []
        self.health_check_interval = int(os.getenv("HEALTH_CHECK_INTERVAL", "300"))  # 5 minutes
        self.metrics_collection_interval = int(os.getenv("METRICS_COLLECTION_INTERVAL", "60"))  # 1 minute
        
    async def start(self):
        """Start all monitoring tasks"""
        if self.running:
            logger.warning("Monitoring tasks already running")
            return
        
        self.running = True
        logger.info("Starting monitoring tasks")
        
        # Start health check task
        health_task = asyncio.create_task(self._health_check_loop())
        self.tasks.append(health_task)
        
        # Start metrics collection task
        metrics_task = asyncio.create_task(self._metrics_collection_loop())
        self.tasks.append(metrics_task)
        
        logger.info(f"Started {len(self.tasks)} monitoring tasks")
    
    async def stop(self):
        """Stop all monitoring tasks"""
        if not self.running:
            return
        
        self.running = False
        logger.info("Stopping monitoring tasks")
        
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        self.tasks.clear()
        logger.info("All monitoring tasks stopped")
    
    async def _health_check_loop(self):
        """Periodic health check and alerting loop"""
        logger.info(f"Starting health check loop (interval: {self.health_check_interval}s)")
        
        while self.running:
            try:
                await self._run_health_check()
                await asyncio.sleep(self.health_check_interval)
            except asyncio.CancelledError:
                logger.info("Health check loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
                # Continue running even if there's an error
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _metrics_collection_loop(self):
        """Periodic metrics collection loop"""
        logger.info(f"Starting metrics collection loop (interval: {self.metrics_collection_interval}s)")
        
        while self.running:
            try:
                await self._collect_metrics()
                await asyncio.sleep(self.metrics_collection_interval)
            except asyncio.CancelledError:
                logger.info("Metrics collection loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                # Continue running even if there's an error
                await asyncio.sleep(30)  # Wait 30 seconds before retrying
    
    async def _run_health_check(self):
        """Run health check and process alerts"""
        try:
            async with get_async_session() as db:
                # Initialize services
                email_service = EmailService()
                alerting_service = AlertingService(db, email_service)
                
                # Run health checks
                alerts = await alerting_service.check_system_health()
                
                if alerts:
                    logger.info(f"Health check completed: {len(alerts)} alerts generated")
                    for alert in alerts:
                        logger.info(f"Alert: [{alert.severity}] {alert.type} - {alert.message}")
                else:
                    logger.debug("Health check completed: no alerts")
                    
        except Exception as e:
            logger.error(f"Health check failed: {e}")
    
    async def _collect_metrics(self):
        """Collect and cache metrics"""
        try:
            async with get_async_session() as db:
                metrics_service = MetricsService(db)
                
                # Collect system metrics (this will update the cache)
                metrics = await metrics_service.get_system_metrics()
                
                # Log key metrics
                app_metrics = metrics.get("application", {})
                business_metrics = metrics.get("business", {})
                
                logger.debug(
                    f"Metrics collected - Workspaces: {app_metrics.get('total_workspaces', 0)}, "
                    f"Messages (month): {business_metrics.get('current_month', {}).get('messages_sent', 0)}, "
                    f"Active conversations: {sum(business_metrics.get('conversations_by_status', {}).values())}"
                )
                
        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")

# Global task manager instance
monitoring_task_manager = MonitoringTaskManager()

async def start_monitoring_tasks():
    """Start monitoring background tasks"""
    await monitoring_task_manager.start()

async def stop_monitoring_tasks():
    """Stop monitoring background tasks"""
    await monitoring_task_manager.stop()

# Health check function for manual execution
async def run_manual_health_check() -> dict:
    """Run a manual health check and return results"""
    try:
        async with get_async_session() as db:
            email_service = EmailService()
            alerting_service = AlertingService(db, email_service)
            
            alerts = await alerting_service.check_system_health()
            
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "alert_count": len(alerts),
                "alerts": [
                    {
                        "type": alert.type,
                        "severity": alert.severity,
                        "message": alert.message,
                        "details": alert.details,
                        "workspace_id": alert.workspace_id
                    }
                    for alert in alerts
                ],
                "status": "critical" if any(alert.severity == "critical" for alert in alerts) else
                         "warning" if alerts else "healthy"
            }
            
    except Exception as e:
        logger.error(f"Manual health check failed: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error": str(e)
        }

# Metrics collection function for manual execution
async def collect_manual_metrics() -> dict:
    """Collect metrics manually and return results"""
    try:
        async with get_async_session() as db:
            metrics_service = MetricsService(db)
            metrics = await metrics_service.get_system_metrics()
            return metrics
            
    except Exception as e:
        logger.error(f"Manual metrics collection failed: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }