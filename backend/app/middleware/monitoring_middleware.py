"""
Monitoring Middleware

Collects request metrics and performance data for monitoring.
Implemented as pure ASGI middleware (not BaseHTTPMiddleware) to avoid the
known Starlette bug where BaseHTTPMiddleware mishandles anyio ExceptionGroups
on Python 3.11+, causing spurious "No response returned." RuntimeErrors.
"""

import asyncio
import time
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.requests import Request

logger = logging.getLogger(__name__)


class MonitoringMiddleware:
    """Pure-ASGI middleware to collect HTTP request metrics"""

    def __init__(self, app: ASGIApp, max_history: int = 1000) -> None:
        self.app = app
        self.max_history = max_history
        self.request_history: deque = deque(maxlen=max_history)
        self.metrics: dict = {
            "total_requests": 0,
            "requests_by_method": defaultdict(int),
            "requests_by_status": defaultdict(int),
            "requests_by_endpoint": defaultdict(int),
            "response_times": deque(maxlen=100),
            "error_count": 0,
            "active_requests": 0,
        }
        self.lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        start_time = time.time()
        endpoint = self._get_endpoint_pattern(request)
        status_code = 500

        async with self.lock:
            self.metrics["active_requests"] += 1

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                headers = list(message.get("headers", []))
                response_time = time.time() - start_time
                headers.append((b"x-response-time", f"{response_time:.3f}s".encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            response_time = time.time() - start_time
            await self._record_request_metrics(request, status_code, response_time, endpoint)
        except Exception as e:
            response_time = time.time() - start_time
            await self._record_error_metrics(request, e, response_time, endpoint)
            raise
        finally:
            async with self.lock:
                self.metrics["active_requests"] -= 1

    def _get_endpoint_pattern(self, request: Request) -> str:
        path = request.url.path
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
        status_code: int,
        response_time: float,
        endpoint: str,
    ) -> None:
        async with self.lock:
            self.metrics["total_requests"] += 1
            self.metrics["requests_by_method"][request.method] += 1
            self.metrics["requests_by_status"][status_code] += 1
            self.metrics["requests_by_endpoint"][endpoint] += 1
            self.metrics["response_times"].append(response_time)
            if status_code >= 400:
                self.metrics["error_count"] += 1
            self.request_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "endpoint": endpoint,
                "status_code": status_code,
                "response_time": response_time,
                "user_agent": request.headers.get("user-agent", ""),
                "ip": request.client.host if request.client else "unknown",
            })

    async def _record_error_metrics(
        self,
        request: Request,
        error: Exception,
        response_time: float,
        endpoint: str,
    ) -> None:
        async with self.lock:
            self.metrics["total_requests"] += 1
            self.metrics["requests_by_method"][request.method] += 1
            self.metrics["requests_by_status"][500] += 1
            self.metrics["requests_by_endpoint"][endpoint] += 1
            self.metrics["error_count"] += 1
            self.metrics["response_times"].append(response_time)
            self.request_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "endpoint": endpoint,
                "status_code": 500,
                "response_time": response_time,
                "error": str(error),
                "user_agent": request.headers.get("user-agent", ""),
                "ip": request.client.host if request.client else "unknown",
            })

        logger.error(f"Request error: {request.method} {endpoint} - {str(error)}")

    async def get_metrics(self) -> dict:
        async with self.lock:
            response_times = list(self.metrics["response_times"])

            if response_times:
                sorted_times = sorted(response_times)
                count = len(sorted_times)
                response_time_stats = {
                    "avg": sum(sorted_times) / count,
                    "min": sorted_times[0],
                    "max": sorted_times[-1],
                    "p50": sorted_times[int(count * 0.5)],
                    "p95": sorted_times[int(count * 0.95)],
                    "p99": sorted_times[int(count * 0.99)] if count > 1 else sorted_times[0],
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
                "response_time_stats": response_time_stats,
            }

    async def get_recent_requests(self, limit: int = 50) -> list:
        async with self.lock:
            return list(self.request_history)[-limit:]

    async def reset_metrics(self) -> None:
        async with self.lock:
            self.metrics = {
                "total_requests": 0,
                "requests_by_method": defaultdict(int),
                "requests_by_status": defaultdict(int),
                "requests_by_endpoint": defaultdict(int),
                "response_times": deque(maxlen=100),
                "error_count": 0,
                "active_requests": 0,
            }
            self.request_history.clear()


monitoring_middleware: MonitoringMiddleware | None = None


def get_monitoring_middleware() -> MonitoringMiddleware:
    if monitoring_middleware is None:
        raise RuntimeError("Monitoring middleware not initialized")
    return monitoring_middleware


def init_monitoring_middleware(app: ASGIApp) -> MonitoringMiddleware:
    global monitoring_middleware
    monitoring_middleware = MonitoringMiddleware(app)
    return monitoring_middleware
