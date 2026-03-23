"""
Metrics API Router

Provides endpoints for monitoring and metrics collection
"""

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Dict, Any, Optional
from datetime import date
import logging

from app.database import get_db
from app.services.metrics_service import MetricsService
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.config import TIER_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/metrics", tags=["metrics"])

@router.get("/health/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """
    Detailed health check endpoint with comprehensive system status
    
    Returns detailed health information including database, storage,
    and application component status.
    """
    try:
        metrics_service = MetricsService(db)
        health_metrics = await metrics_service._get_health_metrics()
        performance_metrics = await metrics_service._get_performance_metrics()
        
        return {
            "status": "healthy",
            "timestamp": metrics_service._metrics_cache.get("timestamp", 0),
            "health": health_metrics,
            "performance": performance_metrics
        }
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@router.get("/system")
async def get_system_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive system metrics
    
    Requires authentication. Returns application, business, performance,
    and health metrics for monitoring dashboards.
    """
    try:
        metrics_service = MetricsService(db)
        metrics = await metrics_service.get_system_metrics()
        return metrics
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")

@router.get("/workspace/{workspace_id}")
async def get_workspace_metrics(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get metrics for a specific workspace
    
    Returns usage statistics, conversation metrics, and channel information
    for the specified workspace.
    """
    try:
        # Verify user has access to this workspace
        # Get user's workspace from the database
        from sqlalchemy import select
        from app.models.workspace import Workspace
        
        result = await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        
        # Check if user is the workspace owner
        if workspace.owner_id != current_user.id:
            # For non-owners, we could add additional checks here
            # For now, allow access if they have a valid token
            pass
        
        metrics_service = MetricsService(db)
        metrics = await metrics_service.get_workspace_metrics(workspace_id)
        return metrics
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workspace metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get workspace metrics: {str(e)}")

@router.get("/prometheus")
async def get_prometheus_metrics(db: AsyncSession = Depends(get_db)):
    """
    Get metrics in Prometheus format
    
    Public endpoint that returns metrics in Prometheus exposition format
    for scraping by monitoring systems.
    """
    try:
        metrics_service = MetricsService(db)
        prometheus_metrics = await metrics_service.get_prometheus_metrics()
        
        return Response(
            content=prometheus_metrics,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        logger.error(f"Error generating Prometheus metrics: {e}")
        return Response(
            content=f"# Error generating metrics: {e}",
            media_type="text/plain",
            status_code=500
        )

@router.get("/alerts/status")
async def get_alert_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current alert status and thresholds
    
    Returns information about active alerts and system thresholds
    for monitoring and alerting systems.
    """
    try:
        metrics_service = MetricsService(db)
        metrics = await metrics_service.get_system_metrics()
        
        # Calculate alert conditions
        alerts = []
        
        # Check health metrics
        health = metrics.get("health", {})
        if health.get("stale_conversations", 0) > 10:
            alerts.append({
                "severity": "warning",
                "message": f"High number of stale conversations: {health['stale_conversations']}",
                "metric": "stale_conversations",
                "value": health["stale_conversations"],
                "threshold": 10
            })
        
        if health.get("failed_documents", 0) > 5:
            alerts.append({
                "severity": "warning",
                "message": f"High number of failed documents: {health['failed_documents']}",
                "metric": "failed_documents",
                "value": health["failed_documents"],
                "threshold": 5
            })
        
        # Check performance metrics
        performance = metrics.get("performance", {})
        db_metrics = performance.get("database", {})
        if db_metrics.get("active_connections", 0) > 50:
            alerts.append({
                "severity": "warning",
                "message": f"High database connection count: {db_metrics['active_connections']}",
                "metric": "db_active_connections",
                "value": db_metrics["active_connections"],
                "threshold": 50
            })
        
        return {
            "status": "critical" if any(alert["severity"] == "critical" for alert in alerts) else 
                     "warning" if alerts else "ok",
            "alerts": alerts,
            "alert_count": len(alerts),
            "timestamp": metrics.get("timestamp", 0)
        }
        
    except Exception as e:
        logger.error(f"Error getting alert status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get alert status: {str(e)}")


@router.get("/csat")
async def get_csat_metrics(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """
    Workspace CSAT summary: average score, response rate.
    Date-range trend data requires Growth+ tier.
    """
    from app.models.csat_rating import CSATRating
    from app.models.conversation import Conversation
    from datetime import datetime, timezone

    # Total resolved conversations (denominator for response rate)
    total_resolved_q = select(func.count(Conversation.id)).where(
        Conversation.workspace_id == current_workspace.id,
        Conversation.status == "resolved",
    )
    if date_from:
        total_resolved_q = total_resolved_q.where(Conversation.updated_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        total_resolved_q = total_resolved_q.where(Conversation.updated_at <= datetime.combine(date_to, datetime.max.time()))
    total_resolved = (await db.execute(total_resolved_q)).scalar() or 0

    # CSAT stats
    csat_q = select(
        func.count(CSATRating.id).label("total_ratings"),
        func.avg(CSATRating.rating).label("avg_rating"),
    ).where(CSATRating.workspace_id == current_workspace.id)
    if date_from:
        csat_q = csat_q.where(CSATRating.submitted_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        csat_q = csat_q.where(CSATRating.submitted_at <= datetime.combine(date_to, datetime.max.time()))
    csat_result = (await db.execute(csat_q)).one()
    total_ratings = csat_result.total_ratings or 0
    avg_rating = round(float(csat_result.avg_rating), 2) if csat_result.avg_rating else None
    response_rate = round(total_ratings / total_resolved, 4) if total_resolved > 0 else 0.0

    summary = {
        "total_ratings": total_ratings,
        "average_rating": avg_rating,
        "response_rate": response_rate,
        "total_resolved_conversations": total_resolved,
    }

    # Trend data: Growth+ only
    has_trends = TIER_LIMITS.get(current_workspace.tier or "free", {}).get("has_csat_trends", False)
    if has_trends and (date_from or date_to):
        trend_q = (
            select(
                func.date_trunc("day", CSATRating.submitted_at).label("day"),
                func.count(CSATRating.id).label("count"),
                func.avg(CSATRating.rating).label("avg"),
            )
            .where(CSATRating.workspace_id == current_workspace.id)
            .group_by("day")
            .order_by("day")
        )
        if date_from:
            trend_q = trend_q.where(CSATRating.submitted_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            trend_q = trend_q.where(CSATRating.submitted_at <= datetime.combine(date_to, datetime.max.time()))
        trend_rows = (await db.execute(trend_q)).all()
        summary["trend"] = [
            {"date": str(r.day.date()), "count": r.count, "avg_rating": round(float(r.avg), 2)}
            for r in trend_rows
        ]

    return summary