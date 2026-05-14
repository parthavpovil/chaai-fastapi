"""
ChatSaaS Backend - FastAPI Application Entry Point
"""
import asyncio
import functools
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

# Initialize logging first
from logging_config import setup_logging
logger = setup_logging()

from app.config import settings
from app.database import init_db, close_db
from app.routers import auth, webchat, admin, agents, channels, webhooks, websocket, documents, conversations, metrics
from app.routers import canned_responses, assignment_rules as assignment_rules_router, outbound_webhooks as outbound_webhooks_router, api_keys as api_keys_router, billing as billing_router, workspace as workspace_router
from app.routers import contacts as contacts_router, business_hours as business_hours_router
from app.routers import flows as flows_router, templates as templates_router, broadcasts as broadcasts_router
from app.routers import ai_agents as ai_agents_router
from app.routers import websocket_webchat
from app.routers import permissions as permissions_router
from app.routers import admin_permissions as admin_permissions_router
from app.middleware.maintenance_middleware import MaintenanceModeMiddleware
from app.middleware.monitoring_middleware import init_monitoring_middleware, MonitoringMiddleware
from app.middleware.request_id_middleware import RequestIDMiddleware


def _init_sentry() -> None:
    """Init Sentry SDK if SENTRY_DSN is configured. Scrubs auth headers before sending."""
    if not settings.SENTRY_DSN:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    _SENSITIVE_HEADERS = frozenset({
        "authorization", "cookie", "x-api-key", "x-process-secret",
    })

    def _before_send(event, hint):
        headers = (event.get("request") or {}).get("headers") or {}
        for h in list(headers):
            if h.lower() in _SENSITIVE_HEADERS:
                headers[h] = "[Filtered]"
        return event

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        before_send=_before_send,
    )
    logger.info("Sentry initialised (traces_sample_rate=%.2f)", settings.SENTRY_TRACES_SAMPLE_RATE)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan manager.

    Web workers run ONLY per-worker tasks (stale-WS cleanup, Redis pub/sub
    listener — both operate on local in-memory state). Recurring singleton
    jobs (monitoring, agent-status, reconciliation, metrics) run in the
    dedicated arq worker container — see app/tasks/scheduled_jobs.py.
    """
    _init_sentry()
    await init_db()

    cleanup_task = asyncio.create_task(
        websocket_webchat.cleanup_stale_customer_connections()
    )

    from app.services.redis_pubsub import redis_pubsub
    from app.services.websocket_manager import websocket_manager, customer_websocket_manager

    async def _redis_dispatch(channel: str, message: dict) -> None:
        if channel.startswith("ws:agent:"):
            workspace_id = channel[len("ws:agent:"):]
            await websocket_manager.deliver_to_local(workspace_id, message)
        elif channel.startswith("ws:customer:"):
            workspace_id = channel[len("ws:customer:"):]
            await customer_websocket_manager.deliver_to_local(workspace_id, message)

    pubsub_task = asyncio.create_task(redis_pubsub.start_listener(_redis_dispatch))

    yield

    cleanup_task.cancel()
    pubsub_task.cancel()
    await close_db()


# Create FastAPI application
app = FastAPI(
    title="ChatSaaS Backend",
    description="Multi-tenant customer support platform with AI-powered responses",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Prometheus metrics — exposes GET /metrics (Prometheus scrape format).
# Currently disabled while we verify the BaseHTTPMiddleware → pure-ASGI
# migration below resolves the lifespan-startup hang. Re-enable once the
# fix is confirmed in production.
# from prometheus_fastapi_instrumentator import Instrumentator
# Instrumentator().instrument(app).expose(app, include_in_schema=False)


# Configure CORS
# /api/webchat/* and /ws/webchat/* are public widget endpoints — any origin is allowed
# because the widget is embedded on arbitrary customer websites we don't know in advance.
# All other routes (dashboard, agent API) use the strict ALLOWED_ORIGINS allowlist.
# Abuse prevention on webchat routes is handled by widget_id validation, session tokens,
# and rate limiting — not by CORS.

_WEBCHAT_PREFIXES = ("/api/webchat/", "/ws/webchat/", "/static/")


def _origin_matches_allowed_origin(origin: str, allowed_origin: str) -> bool:
    if origin == allowed_origin:
        return True

    origin_parts = urlparse(origin)
    allowed_parts = urlparse(allowed_origin)

    if origin_parts.scheme != allowed_parts.scheme:
        return False

    allowed_host = allowed_parts.hostname or ""
    origin_host = origin_parts.hostname or ""

    if not allowed_host or not origin_host:
        return False

    return origin_host == allowed_host or origin_host.endswith(f".{allowed_host}")

class SplitCORSMiddleware:
    """Pure-ASGI CORS middleware (not BaseHTTPMiddleware).

    BaseHTTPMiddleware in Starlette 0.37.x interacts badly with the
    lifespan handshake under gunicorn's UvicornWorker — even though it
    forwards non-HTTP scopes, its construction sets up anyio state that
    can prevent uvicorn from observing lifespan.startup.complete. Pure
    ASGI middleware avoids that entirely.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_webchat = any(path.startswith(p) for p in _WEBCHAT_PREFIXES)

        origin = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"origin":
                origin = header_value.decode("latin-1", errors="replace")
                break

        if is_webchat:
            cors_headers = [
                (b"access-control-allow-origin", b"*"),
                (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                (b"access-control-allow-headers", b"Content-Type, Authorization"),
            ]
        elif origin and any(
            _origin_matches_allowed_origin(origin, allowed_origin)
            for allowed_origin in settings.ALLOWED_ORIGINS
        ):
            cors_headers = [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-credentials", b"true"),
                (b"access-control-allow-methods", b"*"),
                (b"access-control-allow-headers", b"*"),
                (b"vary", b"Origin"),
            ]
        else:
            cors_headers = []

        if scope.get("method") == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": cors_headers,
            })
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: dict) -> None:
            if message["type"] == "http.response.start" and cors_headers:
                headers = list(message.get("headers", []))
                headers.extend(cors_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


# Middleware stack — last-added wraps all previous, so execution order
# on a request is: RequestID → Monitoring → Maintenance → SplitCORS → app.
app.add_middleware(SplitCORSMiddleware)
app.add_middleware(MaintenanceModeMiddleware)

monitoring_middleware = init_monitoring_middleware(app)
app.add_middleware(MonitoringMiddleware, max_history=1000)

# Request-ID middleware — outermost so every downstream log line carries the ID.
app.add_middleware(RequestIDMiddleware)

# Mount static files (widget.js, etc.)
import os
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(webchat.router)
app.include_router(admin.router)
app.include_router(agents.router)
app.include_router(channels.router)
app.include_router(webhooks.router)
app.include_router(websocket.router)
app.include_router(documents.router)
app.include_router(conversations.router)
app.include_router(metrics.router)
app.include_router(canned_responses.router)
app.include_router(assignment_rules_router.router)
app.include_router(outbound_webhooks_router.router)
app.include_router(api_keys_router.router)
app.include_router(billing_router.router)
app.include_router(workspace_router.router)
app.include_router(contacts_router.router)
app.include_router(business_hours_router.router)
app.include_router(flows_router.router)
app.include_router(templates_router.router)
app.include_router(broadcasts_router.router)
app.include_router(ai_agents_router.router)
app.include_router(permissions_router.router)
app.include_router(admin_permissions_router.router)
app.include_router(websocket_webchat.router)

# ── Global exception handlers ─────────────────────────────────────────────────
# All three handlers inject the X-Request-ID into the response body so operators
# can correlate a client-reported error with the log lines from that request.

from app.utils.request_context import get_request_id as _get_request_id


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalize HTTPException responses and add request_id.

    Preserves exc.headers (e.g. WWW-Authenticate: Bearer on 401s).
    For 5xx responses the internal detail is logged but NOT sent to the client
    to prevent accidental leakage of table names, query fragments, or data values.
    """
    if exc.status_code >= 500:
        logger.error(
            "HTTP %s: %s %s rid=%s — %s",
            exc.status_code, request.method, request.url.path,
            _get_request_id(), exc.detail,
        )
        safe_detail = "Internal server error"
    else:
        safe_detail = exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": safe_detail, "request_id": _get_request_id() or None},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 422 validation errors with request_id for client-side debugging."""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": _get_request_id() or None},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions.

    Logs the full traceback (never leaks it to the client) and returns a
    generic 500 with the request_id so the caller can report a correlatable ID.
    """
    logger.error(
        "Unhandled exception: %s %s rid=%s",
        request.method, request.url.path, _get_request_id(),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": _get_request_id() or None},
    )


# ── Health check with result cache ────────────────────────────────────────────
# Load balancers probe /health every few seconds.  Running a DB query and a
# synchronous boto3 head_bucket on every probe burns a DB connection and blocks
# the event loop on the network round-trip.  Cache the result for
# _HEALTH_CACHE_TTL seconds; only one concurrent refresh is allowed (lock).

_HEALTH_CACHE_TTL = 10.0  # seconds
_health_cache: dict | None = None
_health_cache_expires: float = 0.0
_health_cache_lock = asyncio.Lock()


async def _run_health_checks() -> dict:
    start = time.monotonic()
    wall = time.time()
    checks: dict = {
        "status": "healthy",
        "service": "chatsaas-backend",
        "timestamp": wall,
        "checks": {},
    }

    # Database — use engine.connect() directly (lighter than a full session)
    db_start = time.monotonic()
    try:
        from app.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["checks"]["database"] = {
            "status": "healthy",
            "response_time_ms": round((time.monotonic() - db_start) * 1000, 2),
        }
    except Exception as e:
        checks["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        checks["status"] = "unhealthy"

    # R2 — boto3 is synchronous (default connect/read timeouts ≈ 60 s each).
    # Wrap in asyncio.wait_for so a cold/slow R2 connection can't block the
    # endpoint past the 10 s docker healthcheck timeout. A timed-out R2 check
    # is recorded as "unhealthy" in the body but the endpoint still returns
    # 200 within a few seconds — the docker healthcheck only cares that we
    # respond at all.
    r2_start = time.monotonic()
    try:
        from app.services.r2_storage import _get_r2_client
        r2 = _get_r2_client()
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                functools.partial(r2.head_bucket, Bucket=settings.R2_BUCKET_NAME),
            ),
            timeout=3.0,
        )
        checks["checks"]["storage"] = {
            "status": "healthy",
            "backend": "cloudflare-r2",
            "bucket": settings.R2_BUCKET_NAME,
            "response_time_ms": round((time.monotonic() - r2_start) * 1000, 2),
        }
    except asyncio.TimeoutError:
        checks["checks"]["storage"] = {
            "status": "unhealthy",
            "backend": "cloudflare-r2",
            "error": "head_bucket exceeded 3s timeout",
        }
        checks["status"] = "unhealthy"
    except Exception as e:
        checks["checks"]["storage"] = {
            "status": "unhealthy",
            "backend": "cloudflare-r2",
            "error": str(e),
        }
        checks["status"] = "unhealthy"

    checks["response_time_ms"] = round((time.monotonic() - start) * 1000, 2)
    return checks


@app.get("/health")
async def health_check():
    """Health check endpoint for load balancer. Result is cached for 10 s."""
    global _health_cache, _health_cache_expires

    # Fast path — return cached result without acquiring the lock
    now = time.monotonic()
    if _health_cache is not None and now < _health_cache_expires:
        return _health_cache

    # Slow path — one coroutine refreshes; others wait and then use the result
    async with _health_cache_lock:
        now = time.monotonic()
        if _health_cache is not None and now < _health_cache_expires:
            return _health_cache

        result = await _run_health_checks()
        _health_cache = result
        _health_cache_expires = time.monotonic() + _HEALTH_CACHE_TTL
        return result

@app.get("/metrics/middleware")
async def get_middleware_metrics():
    """Get middleware-collected metrics"""
    try:
        from app.middleware.monitoring_middleware import get_monitoring_middleware
        middleware = get_monitoring_middleware()
        return await middleware.get_metrics()
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info"
    )