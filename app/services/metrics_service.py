"""
Metrics Collection Service

Provides application metrics for monitoring and alerting
"""

import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from collections import defaultdict
import asyncio
import logging

from app.models.workspace import Workspace
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.usage_counter import UsageCounter
from app.models.document import Document
from app.models.agent import Agent
from app.models.channel import Channel

logger = logging.getLogger(__name__)

class MetricsService:
    """Service for collecting and exposing application metrics"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._metrics_cache = {}
        self._cache_ttl = 60  # Cache metrics for 60 seconds
        self._last_cache_update = 0
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        current_time = time.time()
        
        # Use cached metrics if still valid
        if (current_time - self._last_cache_update) < self._cache_ttl and self._metrics_cache:
            return self._metrics_cache
        
        metrics = {
            "timestamp": current_time,
            "application": await self._get_application_metrics(),
            "business": await self._get_business_metrics(),
            "performance": await self._get_performance_metrics(),
            "health": await self._get_health_metrics()
        }
        
        # Update cache
        self._metrics_cache = metrics
        self._last_cache_update = current_time
        
        return metrics
    
    async def _get_application_metrics(self) -> Dict[str, Any]:
        """Get application-level metrics"""
        try:
            # Total workspaces by tier
            workspace_stats = await self.db.execute(
                select(
                    Workspace.tier,
                    func.count(Workspace.id).label('count')
                )
                .where(Workspace.is_active == True)
                .group_by(Workspace.tier)
            )
            
            workspace_by_tier = {row.tier: row.count for row in workspace_stats}
            
            # Total active channels
            channel_stats = await self.db.execute(
                select(
                    Channel.type,
                    func.count(Channel.id).label('count')
                )
                .where(Channel.is_active == True)
                .group_by(Channel.type)
            )
            
            channels_by_type = {row.type: row.count for row in channel_stats}
            
            # Total active agents
            agent_count = await self.db.execute(
                select(func.count(Agent.id))
                .where(Agent.is_active == True)
            )
            
            return {
                "workspaces_by_tier": workspace_by_tier,
                "channels_by_type": channels_by_type,
                "active_agents": agent_count.scalar() or 0,
                "total_workspaces": sum(workspace_by_tier.values()),
                "total_channels": sum(channels_by_type.values())
            }
            
        except Exception as e:
            logger.error(f"Error getting application metrics: {e}")
            return {"error": str(e)}
    
    async def _get_business_metrics(self) -> Dict[str, Any]:
        """Get business-level metrics"""
        try:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            
            # Current month usage
            current_usage = await self.db.execute(
                select(
                    func.sum(UsageCounter.messages_sent).label('total_messages'),
                    func.sum(UsageCounter.tokens_used).label('total_tokens'),
                    func.count(UsageCounter.workspace_id).label('active_workspaces')
                )
                .where(UsageCounter.month == current_month)
            )
            
            usage_stats = current_usage.first()
            
            # Active conversations by status
            conversation_stats = await self.db.execute(
                select(
                    Conversation.status,
                    func.count(Conversation.id).label('count')
                )
                .group_by(Conversation.status)
            )
            
            conversations_by_status = {row.status: row.count for row in conversation_stats}
            
            # Messages by sender type (last 24 hours)
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            message_stats = await self.db.execute(
                select(
                    Message.role,
                    func.count(Message.id).label('count')
                )
                .where(Message.created_at >= yesterday)
                .group_by(Message.role)
            )
            
            messages_by_sender = {row.role: row.count for row in message_stats}
            
            # Document processing status
            document_stats = await self.db.execute(
                select(
                    Document.status,
                    func.count(Document.id).label('count')
                )
                .group_by(Document.status)
            )
            
            documents_by_status = {row.status: row.count for row in document_stats}
            
            return {
                "current_month": {
                    "messages_sent": usage_stats.total_messages or 0,
                    "tokens_used": usage_stats.total_tokens or 0,
                    "active_workspaces": usage_stats.active_workspaces or 0
                },
                "conversations_by_status": conversations_by_status,
                "messages_last_24h": messages_by_sender,
                "documents_by_status": documents_by_status,
                "escalation_rate": self._calculate_escalation_rate(conversations_by_status)
            }
            
        except Exception as e:
            logger.error(f"Error getting business metrics: {e}")
            return {"error": str(e)}
    
    async def _get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance-related metrics"""
        try:
            # Database connection pool stats
            db_stats = await self.db.execute(
                text("""
                    SELECT 
                        count(*) as total_connections,
                        count(*) FILTER (WHERE state = 'active') as active_connections,
                        count(*) FILTER (WHERE state = 'idle') as idle_connections
                    FROM pg_stat_activity 
                    WHERE datname = current_database()
                """)
            )
            
            db_result = db_stats.first()
            
            # Average response times (simulated - would need actual instrumentation)
            # This would typically come from middleware or instrumentation
            
            return {
                "database": {
                    "total_connections": db_result.total_connections,
                    "active_connections": db_result.active_connections,
                    "idle_connections": db_result.idle_connections
                },
                "response_times": {
                    "avg_response_time_ms": 150,  # Would be calculated from actual metrics
                    "p95_response_time_ms": 500,  # Would be calculated from actual metrics
                    "p99_response_time_ms": 1000  # Would be calculated from actual metrics
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            return {"error": str(e)}
    
    async def _get_health_metrics(self) -> Dict[str, Any]:
        """Get health-related metrics"""
        try:
            # Check for recent errors (would need error tracking table)
            # For now, return basic health indicators
            
            # Check for stale conversations (no activity in 24 hours)
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            stale_conversations = await self.db.execute(
                select(func.count(Conversation.id))
                .where(
                    Conversation.status.in_(['escalated', 'agent']),
                    Conversation.updated_at < yesterday
                )
            )
            
            # Check for failed document processing
            failed_documents = await self.db.execute(
                select(func.count(Document.id))
                .where(Document.status == 'failed')
            )
            
            return {
                "stale_conversations": stale_conversations.scalar() or 0,
                "failed_documents": failed_documents.scalar() or 0,
                "health_score": self._calculate_health_score()
            }
            
        except Exception as e:
            logger.error(f"Error getting health metrics: {e}")
            return {"error": str(e)}
    
    def _calculate_escalation_rate(self, conversations_by_status: Dict[str, int]) -> float:
        """Calculate escalation rate as percentage"""
        total_conversations = sum(conversations_by_status.values())
        if total_conversations == 0:
            return 0.0
        
        escalated = conversations_by_status.get('escalated', 0) + conversations_by_status.get('agent', 0)
        return round((escalated / total_conversations) * 100, 2)
    
    def _calculate_health_score(self) -> float:
        """Calculate overall health score (0-100)"""
        # Simple health score calculation
        # In production, this would be more sophisticated
        return 95.0
    
    async def get_workspace_metrics(self, workspace_id: str) -> Dict[str, Any]:
        """Get metrics for a specific workspace"""
        try:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            
            # Workspace usage
            usage_stats = await self.db.execute(
                select(UsageCounter)
                .where(
                    UsageCounter.workspace_id == workspace_id,
                    UsageCounter.month == current_month
                )
            )
            
            usage = usage_stats.scalar_one_or_none()
            
            # Conversation stats
            conversation_stats = await self.db.execute(
                select(
                    Conversation.status,
                    func.count(Conversation.id).label('count')
                )
                .where(Conversation.workspace_id == workspace_id)
                .group_by(Conversation.status)
            )
            
            conversations = {row.status: row.count for row in conversation_stats}
            
            # Channel stats
            channel_stats = await self.db.execute(
                select(
                    Channel.type,
                    func.count(Channel.id).label('count')
                )
                .where(
                    Channel.workspace_id == workspace_id,
                    Channel.is_active == True
                )
                .group_by(Channel.type)
            )
            
            channels = {row.type: row.count for row in channel_stats}
            
            return {
                "workspace_id": workspace_id,
                "current_month_usage": {
                    "messages_sent": usage.messages_sent if usage else 0,
                    "tokens_used": usage.tokens_used if usage else 0
                },
                "conversations_by_status": conversations,
                "channels_by_type": channels,
                "escalation_rate": self._calculate_escalation_rate(conversations)
            }
            
        except Exception as e:
            logger.error(f"Error getting workspace metrics for {workspace_id}: {e}")
            return {"error": str(e)}

    async def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format"""
        try:
            metrics = await self.get_system_metrics()
            prometheus_output = []
            
            # Application metrics
            app_metrics = metrics.get("application", {})
            if "total_workspaces" in app_metrics:
                prometheus_output.append(f"chatsaas_workspaces_total {app_metrics['total_workspaces']}")
            if "total_channels" in app_metrics:
                prometheus_output.append(f"chatsaas_channels_total {app_metrics['total_channels']}")
            if "active_agents" in app_metrics:
                prometheus_output.append(f"chatsaas_agents_active {app_metrics['active_agents']}")
            
            # Business metrics
            business_metrics = metrics.get("business", {})
            current_month = business_metrics.get("current_month", {})
            if "messages_sent" in current_month:
                prometheus_output.append(f"chatsaas_messages_sent_total {current_month['messages_sent']}")
            if "tokens_used" in current_month:
                prometheus_output.append(f"chatsaas_tokens_used_total {current_month['tokens_used']}")
            
            # Performance metrics
            perf_metrics = metrics.get("performance", {})
            db_metrics = perf_metrics.get("database", {})
            if "active_connections" in db_metrics:
                prometheus_output.append(f"chatsaas_db_connections_active {db_metrics['active_connections']}")
            
            # Health metrics
            health_metrics = metrics.get("health", {})
            if "health_score" in health_metrics:
                prometheus_output.append(f"chatsaas_health_score {health_metrics['health_score']}")
            if "stale_conversations" in health_metrics:
                prometheus_output.append(f"chatsaas_conversations_stale {health_metrics['stale_conversations']}")
            
            return "\n".join(prometheus_output)
            
        except Exception as e:
            logger.error(f"Error generating Prometheus metrics: {e}")
            return f"# Error generating metrics: {e}"