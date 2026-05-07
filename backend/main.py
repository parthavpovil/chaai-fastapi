"""
ChatSaaS Backend - FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
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
from app.middleware.maintenance_middleware import maintenance_mode_middleware
from app.middleware.monitoring_middleware import init_monitoring_middleware, MonitoringMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    await init_db()
    
    # Start monitoring tasks in production
    if not settings.DEBUG:
        from app.tasks.monitoring_tasks import start_monitoring_tasks
        await start_monitoring_tasks()

    # Start agent status heartbeat check
    from app.tasks.agent_status_tasks import start_agent_status_tasks
    await start_agent_status_tasks()

    # Start reconciliation sweeper — re-enqueues orphaned webchat messages
    from app.tasks.reconciliation import start_reconciliation_sweeper
    await start_reconciliation_sweeper()

    # Start customer WebSocket stale-connection cleanup
    import asyncio
    asyncio.create_task(websocket_webchat.cleanup_stale_customer_connections())

    # Start Redis pub/sub listener — forwards cross-worker broadcasts to local WS connections
    from app.services.redis_pubsub import redis_pubsub
    from app.services.websocket_manager import websocket_manager, customer_websocket_manager

    async def _redis_dispatch(channel: str, message: dict) -> None:
        if channel.startswith("ws:agent:"):
            workspace_id = channel[len("ws:agent:"):]
            await websocket_manager.deliver_to_local(workspace_id, message)
        elif channel.startswith("ws:customer:"):
            workspace_id = channel[len("ws:customer:"):]
            await customer_websocket_manager.deliver_to_local(workspace_id, message)

    asyncio.create_task(redis_pubsub.start_listener(_redis_dispatch))

    yield
    
    # Shutdown
    if not settings.DEBUG:
        from app.tasks.monitoring_tasks import stop_monitoring_tasks
        await stop_monitoring_tasks()

    from app.tasks.agent_status_tasks import stop_agent_status_tasks
    await stop_agent_status_tasks()

    from app.tasks.reconciliation import stop_reconciliation_sweeper
    await stop_reconciliation_sweeper()

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

# Configure CORS
# /api/webchat/* and /ws/webchat/* are public widget endpoints — any origin is allowed
# because the widget is embedded on arbitrary customer websites we don't know in advance.
# All other routes (dashboard, agent API) use the strict ALLOWED_ORIGINS allowlist.
# Abuse prevention on webchat routes is handled by widget_id validation, session tokens,
# and rate limiting — not by CORS.

_WEBCHAT_PREFIXES = ("/api/webchat/", "/ws/webchat/", "/static/")

class SplitCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_webchat = any(path.startswith(p) for p in _WEBCHAT_PREFIXES)
        origin = request.headers.get("origin", "")

        if request.method == "OPTIONS":
            response = Response(status_code=200)
        else:
            response = await call_next(request)

        if is_webchat:
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        elif origin in settings.ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Vary"] = "Origin"

        return response

app.add_middleware(SplitCORSMiddleware)

# Add maintenance mode middleware
app.middleware("http")(maintenance_mode_middleware)

# Add monitoring middleware
monitoring_middleware = init_monitoring_middleware(app)
app.add_middleware(MonitoringMiddleware, max_history=1000)

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

@app.get("/health")
async def health_check():
    """Simple health check endpoint for load balancer"""
    import time
    
    start_time = time.time()
    checks = {
        "status": "healthy",
        "service": "chatsaas-backend",
        "timestamp": time.time(),
        "checks": {}
    }
    
    # Basic database connectivity check
    try:
        from app.database import get_db
        async for db in get_db():
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
            checks["checks"]["database"] = {
                "status": "healthy",
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
            break
    except Exception as e:
        checks["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        checks["status"] = "unhealthy"
    
    # R2 storage connectivity check
    try:
        from app.services.r2_storage import _get_r2_client
        r2 = _get_r2_client()
        r2.head_bucket(Bucket=settings.R2_BUCKET_NAME)
        checks["checks"]["storage"] = {
            "status": "healthy",
            "backend": "cloudflare-r2",
            "bucket": settings.R2_BUCKET_NAME,
        }
    except Exception as e:
        checks["checks"]["storage"] = {
            "status": "unhealthy",
            "backend": "cloudflare-r2",
            "error": str(e),
        }
        checks["status"] = "unhealthy"
    
    checks["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
    
    return checks

@app.get("/metrics/middleware")
async def get_middleware_metrics():
    """Get middleware-collected metrics"""
    try:
        from app.middleware.monitoring_middleware import get_monitoring_middleware
        middleware = get_monitoring_middleware()
        return middleware.get_metrics()
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