"""
Alerting Service

Handles error monitoring, alerting, and notification dispatch
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum
import json
import os
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, update

from app.services.email_service import EmailService
from app.models.workspace import Workspace
from app.models.conversation import Conversation
from app.models.usage_counter import UsageCounter
from app.models.document import Document

logger = logging.getLogger(__name__)

class AlertSeverity(str, Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class AlertType(str, Enum):
    """Types of alerts"""
    SYSTEM_ERROR = "system_error"
    HIGH_ERROR_RATE = "high_error_rate"
    DATABASE_ERROR = "database_error"
    STORAGE_ERROR = "storage_error"
    AI_PROVIDER_ERROR = "ai_provider_error"
    HIGH_RESPONSE_TIME = "high_response_time"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    ESCALATION_BACKLOG = "escalation_backlog"

@dataclass
class Alert:
    """Alert data structure"""
    type: AlertType
    severity: AlertSeverity
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    workspace_id: Optional[str] = None
    resolved: bool = False

class AlertingService:
    """Service for monitoring and alerting"""
    
    def __init__(self, db: AsyncSession, email_service: Optional[EmailService] = None):
        self.db = db
        self.email_service = email_service
        self.alert_thresholds = self._load_alert_thresholds()
        self.active_alerts = {}  # In production, this would be stored in database
        
    def _load_alert_thresholds(self) -> Dict[str, Any]:
        """Load alert thresholds from configuration"""
        return {
            "error_rate_threshold": float(os.getenv("ALERT_ERROR_RATE_THRESHOLD", "0.05")),  # 5%
            "response_time_threshold": float(os.getenv("ALERT_RESPONSE_TIME_THRESHOLD", "2000")),  # 2 seconds
            "db_connection_threshold": int(os.getenv("ALERT_DB_CONNECTION_THRESHOLD", "50")),
            "stale_conversation_threshold": int(os.getenv("ALERT_STALE_CONVERSATION_THRESHOLD", "10")),
            "failed_document_threshold": int(os.getenv("ALERT_FAILED_DOCUMENT_THRESHOLD", "5")),
            "disk_space_threshold_gb": float(os.getenv("ALERT_DISK_SPACE_THRESHOLD", "5.0")),
            "memory_usage_threshold": float(os.getenv("ALERT_MEMORY_USAGE_THRESHOLD", "90.0"))
        }
    
    async def check_system_health(self) -> List[Alert]:
        """Check system health and generate alerts"""
        alerts = []
        
        try:
            # Check database health
            db_alerts = await self._check_database_health()
            alerts.extend(db_alerts)
            
            # Check conversation backlog
            conversation_alerts = await self._check_conversation_backlog()
            alerts.extend(conversation_alerts)
            
            # Check document processing
            document_alerts = await self._check_document_processing()
            alerts.extend(document_alerts)
            
            # Check usage patterns
            usage_alerts = await self._check_usage_patterns()
            alerts.extend(usage_alerts)
            
            # Process new alerts
            for alert in alerts:
                await self._process_alert(alert)
            
            return alerts
            
        except Exception as e:
            logger.error(f"Error during health check: {e}")
            error_alert = Alert(
                type=AlertType.SYSTEM_ERROR,
                severity=AlertSeverity.CRITICAL,
                message=f"Health check system error: {str(e)}",
                details={"error": str(e)},
                timestamp=datetime.now(timezone.utc)
            )
            await self._process_alert(error_alert)
            return [error_alert]
    
    async def _check_database_health(self) -> List[Alert]:
        """Check database health and performance"""
        alerts = []
        
        try:
            # Check connection count
            db_stats = await self.db.execute(
                text("""
                    SELECT 
                        count(*) as total_connections,
                        count(*) FILTER (WHERE state = 'active') as active_connections
                    FROM pg_stat_activity 
                    WHERE datname = current_database()
                """)
            )
            
            result = db_stats.first()
            active_connections = result.active_connections
            
            if active_connections > self.alert_thresholds["db_connection_threshold"]:
                alerts.append(Alert(
                    type=AlertType.DATABASE_ERROR,
                    severity=AlertSeverity.WARNING,
                    message=f"High database connection count: {active_connections}",
                    details={
                        "active_connections": active_connections,
                        "threshold": self.alert_thresholds["db_connection_threshold"]
                    },
                    timestamp=datetime.now(timezone.utc)
                ))
            
            # Check for long-running queries
            long_queries = await self.db.execute(
                text("""
                    SELECT count(*) as long_query_count
                    FROM pg_stat_activity 
                    WHERE state = 'active' 
                    AND query_start < NOW() - INTERVAL '30 seconds'
                    AND datname = current_database()
                """)
            )
            
            long_query_count = long_queries.scalar()
            if long_query_count > 5:
                alerts.append(Alert(
                    type=AlertType.DATABASE_ERROR,
                    severity=AlertSeverity.WARNING,
                    message=f"High number of long-running queries: {long_query_count}",
                    details={"long_query_count": long_query_count},
                    timestamp=datetime.now(timezone.utc)
                ))
                
        except Exception as e:
            alerts.append(Alert(
                type=AlertType.DATABASE_ERROR,
                severity=AlertSeverity.CRITICAL,
                message=f"Database health check failed: {str(e)}",
                details={"error": str(e)},
                timestamp=datetime.now(timezone.utc)
            ))
        
        return alerts
    
    async def _check_conversation_backlog(self) -> List[Alert]:
        """Check for conversation escalation backlog"""
        alerts = []
        
        try:
            # Check for stale escalated conversations
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            stale_conversations = await self.db.execute(
                select(func.count(Conversation.id))
                .where(
                    Conversation.status == 'escalated',
                    Conversation.updated_at < yesterday
                )
            )
            
            stale_count = stale_conversations.scalar() or 0
            
            if stale_count > self.alert_thresholds["stale_conversation_threshold"]:
                alerts.append(Alert(
                    type=AlertType.ESCALATION_BACKLOG,
                    severity=AlertSeverity.WARNING,
                    message=f"High number of stale escalated conversations: {stale_count}",
                    details={
                        "stale_conversations": stale_count,
                        "threshold": self.alert_thresholds["stale_conversation_threshold"]
                    },
                    timestamp=datetime.now(timezone.utc)
                ))
            
            # Check escalation rate by workspace
            escalation_stats = await self.db.execute(
                select(
                    Conversation.workspace_id,
                    func.count(Conversation.id).label('total'),
                    func.count(Conversation.id).filter(
                        Conversation.status.in_(['escalated', 'agent'])
                    ).label('escalated')
                )
                .group_by(Conversation.workspace_id)
                .having(func.count(Conversation.id) > 10)  # Only check workspaces with significant activity
            )
            
            for row in escalation_stats:
                escalation_rate = (row.escalated / row.total) * 100 if row.total > 0 else 0
                
                if escalation_rate > 50:  # More than 50% escalation rate
                    alerts.append(Alert(
                        type=AlertType.ESCALATION_BACKLOG,
                        severity=AlertSeverity.WARNING,
                        message=f"High escalation rate for workspace {row.workspace_id}: {escalation_rate:.1f}%",
                        details={
                            "workspace_id": str(row.workspace_id),
                            "escalation_rate": escalation_rate,
                            "total_conversations": row.total,
                            "escalated_conversations": row.escalated
                        },
                        timestamp=datetime.now(timezone.utc),
                        workspace_id=str(row.workspace_id)
                    ))
                    
        except Exception as e:
            alerts.append(Alert(
                type=AlertType.SYSTEM_ERROR,
                severity=AlertSeverity.WARNING,
                message=f"Conversation backlog check failed: {str(e)}",
                details={"error": str(e)},
                timestamp=datetime.now(timezone.utc)
            ))
        
        return alerts
    
    async def _check_document_processing(self) -> List[Alert]:
        """Check document processing health"""
        alerts = []
        
        try:
            # Check for failed document processing
            failed_docs = await self.db.execute(
                select(func.count(Document.id))
                .where(Document.status == 'failed')
            )
            
            failed_count = failed_docs.scalar() or 0
            
            if failed_count > self.alert_thresholds["failed_document_threshold"]:
                alerts.append(Alert(
                    type=AlertType.SYSTEM_ERROR,
                    severity=AlertSeverity.WARNING,
                    message=f"High number of failed document processing: {failed_count}",
                    details={
                        "failed_documents": failed_count,
                        "threshold": self.alert_thresholds["failed_document_threshold"]
                    },
                    timestamp=datetime.now(timezone.utc)
                ))
            
            # Mark documents stuck in processing as failed so users can retry
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            stuck_result = await self.db.execute(
                select(Document.id)
                .where(
                    Document.status == 'processing',
                    Document.created_at < one_hour_ago
                )
            )
            stuck_ids = [row[0] for row in stuck_result.fetchall()]

            if stuck_ids:
                await self.db.execute(
                    update(Document)
                    .where(Document.id.in_(stuck_ids))
                    .values(
                        status='failed',
                        error_message='Processing timed out. Please retry.',
                    )
                )
                await self.db.commit()
                logger.warning(f"Marked {len(stuck_ids)} stuck document(s) as failed")
                alerts.append(Alert(
                    type=AlertType.SYSTEM_ERROR,
                    severity=AlertSeverity.WARNING,
                    message=f"Marked {len(stuck_ids)} stuck document(s) as failed — users can retry",
                    details={"stuck_documents": len(stuck_ids), "document_ids": stuck_ids},
                    timestamp=datetime.now(timezone.utc)
                ))
                
        except Exception as e:
            alerts.append(Alert(
                type=AlertType.SYSTEM_ERROR,
                severity=AlertSeverity.WARNING,
                message=f"Document processing check failed: {str(e)}",
                details={"error": str(e)},
                timestamp=datetime.now(timezone.utc)
            ))
        
        return alerts
    
    async def _check_usage_patterns(self) -> List[Alert]:
        """Check for unusual usage patterns"""
        alerts = []
        
        try:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            
            # Check for workspaces with unusually high token usage
            high_usage = await self.db.execute(
                select(
                    UsageCounter.workspace_id,
                    UsageCounter.tokens_used,
                    UsageCounter.messages_sent
                )
                .where(
                    UsageCounter.month == current_month,
                    UsageCounter.tokens_used > 100000  # More than 100k tokens
                )
            )
            
            for row in high_usage:
                # Get workspace info
                workspace = await self.db.execute(
                    select(Workspace.business_name, Workspace.tier)
                    .where(Workspace.id == row.workspace_id)
                )
                workspace_info = workspace.first()
                
                if workspace_info:
                    alerts.append(Alert(
                        type=AlertType.RESOURCE_EXHAUSTION,
                        severity=AlertSeverity.INFO,
                        message=f"High token usage for workspace {workspace_info.business_name}: {row.tokens_used:,} tokens",
                        details={
                            "workspace_id": str(row.workspace_id),
                            "business_name": workspace_info.business_name,
                            "tier": workspace_info.tier,
                            "tokens_used": row.tokens_used,
                            "messages_sent": row.messages_sent
                        },
                        timestamp=datetime.now(timezone.utc),
                        workspace_id=str(row.workspace_id)
                    ))
                    
        except Exception as e:
            alerts.append(Alert(
                type=AlertType.SYSTEM_ERROR,
                severity=AlertSeverity.WARNING,
                message=f"Usage pattern check failed: {str(e)}",
                details={"error": str(e)},
                timestamp=datetime.now(timezone.utc)
            ))
        
        return alerts
    
    async def _process_alert(self, alert: Alert):
        """Process and potentially send alert notifications"""
        alert_key = f"{alert.type}_{alert.workspace_id or 'system'}_{hash(alert.message)}"
        
        # Check if this alert is already active (simple deduplication)
        if alert_key in self.active_alerts:
            last_alert_time = self.active_alerts[alert_key]
            # Don't send duplicate alerts within 1 hour
            if (alert.timestamp - last_alert_time).total_seconds() < 3600:
                return
        
        # Record this alert
        self.active_alerts[alert_key] = alert.timestamp
        
        # Log the alert
        log_level = logging.CRITICAL if alert.severity == AlertSeverity.CRITICAL else \
                   logging.WARNING if alert.severity == AlertSeverity.WARNING else \
                   logging.INFO
        
        logger.log(log_level, f"ALERT [{alert.severity.upper()}] {alert.type}: {alert.message}")
        
        # Send email notification for critical alerts
        if alert.severity == AlertSeverity.CRITICAL and self.email_service:
            await self._send_alert_email(alert)
    
    async def _send_alert_email(self, alert: Alert):
        """Send email notification for critical alerts"""
        try:
            admin_email = os.getenv("ADMIN_EMAIL")
            if not admin_email:
                logger.warning("No admin email configured for alert notifications")
                return
            
            subject = f"[CRITICAL ALERT] ChatSaaS Backend - {alert.type}"
            
            body = f"""
            Critical Alert Notification
            
            Type: {alert.type}
            Severity: {alert.severity}
            Time: {alert.timestamp.isoformat()}
            
            Message: {alert.message}
            
            Details:
            {json.dumps(alert.details, indent=2)}
            
            Please investigate immediately.
            
            ---
            ChatSaaS Backend Monitoring System
            """
            
            await self.email_service.send_email(
                to_email=admin_email,
                subject=subject,
                body=body
            )
            
            logger.info(f"Alert email sent to {admin_email} for {alert.type}")
            
        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")
    
    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get currently active alerts"""
        # In production, this would query a database table
        current_time = datetime.now(timezone.utc)
        active = []
        
        for alert_key, alert_time in self.active_alerts.items():
            # Consider alerts active for 24 hours
            if (current_time - alert_time).total_seconds() < 86400:
                active.append({
                    "key": alert_key,
                    "timestamp": alert_time.isoformat(),
                    "age_hours": (current_time - alert_time).total_seconds() / 3600
                })
        
        return active
    
    async def resolve_alert(self, alert_key: str):
        """Mark an alert as resolved"""
        if alert_key in self.active_alerts:
            del self.active_alerts[alert_key]
            logger.info(f"Alert resolved: {alert_key}")