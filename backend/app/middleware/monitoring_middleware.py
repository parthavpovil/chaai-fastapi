"""
Monitoring Middleware

Collects request metrics and performance data for monitoring
"""

import time
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict, deque
from datetime import datetime, timezone
import asyncio
import threading

logger = logging.getLogger(__name__)

class MonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP request metrics"""
    
    def __init__(self, app, max_history: int = 1000):
        super().__init__(app)
        self.max_history = max_history
        self.request_history = deque(maxlen=max_history)
        self.metrics = {
            "total_requests": 0,
            "requests_by_method": defaultdict(int),
            "requests_by_status": defaultdict(int),
            "requests_by_endpoint": defaultdict(int),
            "response_times": deque(maxlen=100),  # Keep last 100 response times
            "error_count": 0,
            "active_requests": 0
        }
        self.lock = threading.Lock()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics"""
        # WebSocket upgrade requests never return an HTTP response — pass through.
        if request.scope.get("type") == "websocket":
            return await call_next(request)

        start_time = time.time()

        # Extract endpoint pattern
        endpoint = self._get_endpoint_pattern(request)
        
        # Increment active requests
        with self.lock:
            self.metrics["active_requests"] += 1
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate response time
            response_time = time.time() - start_time
            
            # Record metrics
            await self._record_request_metrics(
                request=request,
                response=response,
                response_time=response_time,
                endpoint=endpoint
            )
            
            # Add response time header for debugging
            response.headers["X-Response-Time"] = f"{response_time:.3f}s"
            
            return response
            
        except Exception as e:
            # Record error metrics
            response_time = time.time() - start_time
            await self._record_error_metrics(
                request=request,
                error=e,
                response_time=response_time,
                endpoint=endpoint
            )
            raise
        
        finally:
            # Decrement active requests
            with self.lock:
                self.metrics["active_requests"] -= 1
    
    def _get_endpoint_pattern(self, request: Request) -> str:
        """Extract endpoint pattern from request"""
        path = request.url.path
        
        # Normalize common patterns
        if path.startswith("/api/webhooks/"):
            return "/api/webhooks/*"
        elif path.startswith("/api/admin/"):
            return "/api/admin/*"
        elif path.startswith("/api/workspaces/"):
            return "/api/workspaces/*"
        elif path.startswith("/api/conversations/"):
            return "/api/conversations/*"
        elif path.startswith("/api/documents/"):
            return "/api/documents/*"
        elif path.startswith("/api/agents/"):
            return "/api/agents/*"
        elif path.startswith("/api/channels/"):
            return "/api/channels/*"
        elif path.startswith("/api/webchat/"):
            return "/api/webchat/*"
        elif path.startswith("/api/metrics/"):
            return "/api/metrics/*"
        else:
            return path
    
    async def _record_request_metrics(
        self,
        request: Request,
        response: Response,
        response_time: float,
        endpoint: str
    ):
        """Record successful request metrics"""
        with self.lock:
            # Basic counters
            self.metrics["total_requests"] += 1
            self.metrics["requests_by_method"][request.method] += 1
            self.metrics["requests_by_status"][response.status_code] += 1
            self.metrics["requests_by_endpoint"][endpoint] += 1
            
            # Response time tracking
            self.metrics["response_times"].append(response_time)
            
            # Error counting
            if response.status_code >= 400:
                self.metrics["error_count"] += 1
            
            # Request history
            self.request_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "response_time": response_time,
                "user_agent": request.headers.get("user-agent", ""),
                "ip": request.client.host if request.client else "unknown"
            })
    
    async def _record_error_metrics(
        self,
        request: Request,
        error: Exception,
        response_time: float,
        endpoint: str
    ):
        """Record error metrics"""
        with self.lock:
            # Basic counters
            self.metrics["total_requests"] += 1
            self.metrics["requests_by_method"][request.method] += 1
            self.metrics["requests_by_status"][500] += 1  # Assume 500 for unhandled exceptions
            self.metrics["requests_by_endpoint"][endpoint] += 1
            self.metrics["error_count"] += 1
            
            # Response time tracking
            self.metrics["response_times"].append(response_time)
            
            # Request history
            self.request_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "endpoint": endpoint,
                "status_code": 500,
                "response_time": response_time,
                "error": str(error),
                "user_agent": request.headers.get("user-agent", ""),
                "ip": request.client.host if request.client else "unknown"
            })
        
        # Log the error
        logger.error(f"Request error: {request.method} {endpoint} - {str(error)}")
    
    def get_metrics(self) -> dict:
        """Get current metrics snapshot"""
        with self.lock:
            response_times = list(self.metrics["response_times"])
            
            # Calculate response time statistics
            if response_times:
                sorted_times = sorted(response_times)
                count = len(sorted_times)
                
                response_time_stats = {
                    "avg": sum(sorted_times) / count,
                    "min": sorted_times[0],
                    "max": sorted_times[-1],
                    "p50": sorted_times[int(count * 0.5)],
                    "p95": sorted_times[int(count * 0.95)],
                    "p99": sorted_times[int(count * 0.99)] if count > 1 else sorted_times[0]
                }
            else:
                response_time_stats = {
                    "avg": 0, "min": 0, "max": 0, "p50": 0, "p95": 0, "p99": 0
                }
            
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_requests": self.metrics["total_requests"],
                "active_requests": self.metrics["active_requests"],
                "error_count": self.metrics["error_count"],
                "error_rate": (self.metrics["error_count"] / max(self.metrics["total_requests"], 1)) * 100,
                "requests_by_method": dict(self.metrics["requests_by_method"]),
                "requests_by_status": dict(self.metrics["requests_by_status"]),
                "requests_by_endpoint": dict(self.metrics["requests_by_endpoint"]),
                "response_time_stats": response_time_stats
            }
    
    def get_recent_requests(self, limit: int = 50) -> list:
        """Get recent request history"""
        with self.lock:
            return list(self.request_history)[-limit:]
    
    def reset_metrics(self):
        """Reset all metrics (useful for testing)"""
        with self.lock:
            self.metrics = {
                "total_requests": 0,
                "requests_by_method": defaultdict(int),
                "requests_by_status": defaultdict(int),
                "requests_by_endpoint": defaultdict(int),
                "response_times": deque(maxlen=100),
                "error_count": 0,
                "active_requests": 0
            }
            self.request_history.clear()

# Global instance for metrics collection
monitoring_middleware = None

def get_monitoring_middleware() -> MonitoringMiddleware:
    """Get the global monitoring middleware instance"""
    if monitoring_middleware is None:
        raise RuntimeError("Monitoring middleware not initialized")
    return monitoring_middleware

def init_monitoring_middleware(app) -> MonitoringMiddleware:
    """Initialize the monitoring middleware"""
    global monitoring_middleware
    monitoring_middleware = MonitoringMiddleware(app)
    return monitoring_middleware