"""
ChatSaaS Backend - FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    
    yield
    
    # Shutdown
    if not settings.DEBUG:
        from app.tasks.monitoring_tasks import stop_monitoring_tasks
        await stop_monitoring_tasks()

    from app.tasks.agent_status_tasks import stop_agent_status_tasks
    await stop_agent_status_tasks()

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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