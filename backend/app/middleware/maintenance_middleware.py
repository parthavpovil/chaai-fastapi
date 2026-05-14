"""
Maintenance Mode Middleware
Handles maintenance mode checking and admin access control
"""
import asyncio
import logging
import time
from typing import Callable, Optional
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

from app.database import AsyncSessionLocal
from app.models.platform_setting import PlatformSetting
from app.services.auth_service import AuthService
from app.config import settings

# Cache TTL in seconds - maintenance mode is rarely changed
_MAINTENANCE_CACHE_TTL = 30
_maintenance_cache: tuple[bool, Optional[str], float] | None = None  # (is_maintenance, message, expires_at)
_maintenance_check_lock: asyncio.Lock | None = None


def _get_check_lock() -> asyncio.Lock:
    global _maintenance_check_lock
    if _maintenance_check_lock is None:
        _maintenance_check_lock = asyncio.Lock()
    return _maintenance_check_lock


class MaintenanceMode:
    """
    Maintenance mode checker and middleware
    Handles system-wide maintenance mode with admin bypass
    """

    def __init__(self):
        self.maintenance_endpoints = [
            "/api/health",
            "/api/auth/login",
            "/api/admin",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]

    async def is_maintenance_mode(self) -> tuple[bool, Optional[str]]:
        """
        Check if system is in maintenance mode.
        Result is cached for _MAINTENANCE_CACHE_TTL seconds to avoid a DB
        hit on every request. A lock prevents concurrent cache-miss stampedes.

        Returns:
            Tuple of (is_maintenance, maintenance_message)
        """
        global _maintenance_cache

        now = time.monotonic()
        if _maintenance_cache is not None and now < _maintenance_cache[2]:
            return _maintenance_cache[0], _maintenance_cache[1]

        async with _get_check_lock():
            # Re-check inside lock in case another coroutine already refreshed it
            if _maintenance_cache is not None and now < _maintenance_cache[2]:
                return _maintenance_cache[0], _maintenance_cache[1]

            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(PlatformSetting.value)
                        .where(PlatformSetting.key == "maintenance_mode")
                    )
                    maintenance_setting = result.scalar_one_or_none()

                    if maintenance_setting == "true":
                        message_result = await db.execute(
                            select(PlatformSetting.value)
                            .where(PlatformSetting.key == "maintenance_message")
                        )
                        maintenance_message = message_result.scalar_one_or_none()
                        _maintenance_cache = (True, maintenance_message or "System is currently under maintenance.", now + _MAINTENANCE_CACHE_TTL)
                        return True, _maintenance_cache[1]

                    _maintenance_cache = (False, None, now + _MAINTENANCE_CACHE_TTL)
                    return False, None

            except Exception as e:
                logger.error(f"Error checking maintenance mode: {e}", exc_info=True)
                # Fail safe - assume not in maintenance mode; use a short cache to avoid hammering DB
                _maintenance_cache = (False, None, now + _MAINTENANCE_CACHE_TTL)
                return False, None
    
    def is_admin_user(self, request: Request) -> bool:
        """
        Check if request is from admin user
        
        Args:
            request: FastAPI request
        
        Returns:
            True if admin user
        """
        try:
            # Get JWT token from Authorization header
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return False
            
            token = auth_header.split(" ")[1]
            payload = AuthService.decode_access_token(token)
            
            if not payload:
                return False
            
            # Check if user email matches super admin email
            user_email = payload.get("email", "").lower()
            super_admin_email = settings.SUPER_ADMIN_EMAIL.lower()
            
            return user_email == super_admin_email
            
        except Exception:
            return False
    
    def is_allowed_endpoint(self, path: str) -> bool:
        """
        Check if endpoint is allowed during maintenance mode
        
        Args:
            path: Request path
        
        Returns:
            True if endpoint is allowed
        """
        # Allow health checks and admin endpoints
        for allowed_path in self.maintenance_endpoints:
            if path.startswith(allowed_path):
                return True
        
        return False
    
    async def create_maintenance_response(
        self, 
        maintenance_message: str,
        request_path: str
    ) -> JSONResponse:
        """
        Create maintenance mode response
        
        Args:
            maintenance_message: Maintenance message
            request_path: Request path
        
        Returns:
            JSON response with maintenance information
        """
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "Service Unavailable",
                "message": maintenance_message,
                "maintenance_mode": True,
                "requested_path": request_path,
                "retry_after": "Please check back later"
            },
            headers={
                "Retry-After": "3600"  # Suggest retry after 1 hour
            }
        )


# Global maintenance mode instance
maintenance_mode = MaintenanceMode()


class MaintenanceModeMiddleware:
    """Pure-ASGI maintenance mode middleware.

    Implemented as pure ASGI (not via @app.middleware("http")) because that
    decorator wraps the dispatch function in BaseHTTPMiddleware, which sits in
    front of the lifespan protocol. On Starlette 0.37.x + uvicorn 0.29 + the
    gunicorn UvicornWorker, that combination can prevent
    "lifespan.startup.complete" from being delivered to uvicorn, leaving the
    worker stuck "Waiting for application startup." forever.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        try:
            if maintenance_mode.is_allowed_endpoint(request.url.path):
                await self.app(scope, receive, send)
                return

            is_maintenance, maintenance_message = await maintenance_mode.is_maintenance_mode()

            if not is_maintenance:
                await self.app(scope, receive, send)
                return

            if not maintenance_mode.is_admin_user(request):
                response = await maintenance_mode.create_maintenance_response(
                    maintenance_message,
                    request.url.path,
                )
                await response(scope, receive, send)
                return

            async def send_with_admin_headers(message: dict) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-maintenance-mode", b"true"))
                    headers.append((b"x-admin-access", b"true"))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_admin_headers)

        except Exception as e:
            logger.error(f"Maintenance middleware error: {e}", exc_info=True)
            await self.app(scope, receive, send)


# ─── Maintenance Mode Management Functions ────────────────────────────────────

async def enable_maintenance_mode(
    db: AsyncSession,
    message: str = "System is currently under maintenance. Please try again later.",
    admin_email: Optional[str] = None
) -> bool:
    """
    Enable maintenance mode
    
    Args:
        db: Database session
        message: Maintenance message
        admin_email: Admin email for verification
    
    Returns:
        True if enabled successfully
    """
    try:
        # Verify admin access if email provided
        if admin_email and admin_email.lower() != settings.SUPER_ADMIN_EMAIL.lower():
            raise ValueError("Unauthorized: Only super admin can enable maintenance mode")
        
        # Update maintenance mode setting
        from sqlalchemy.dialects.postgresql import insert
        
        # Enable maintenance mode
        stmt = insert(PlatformSetting).values(
            key="maintenance_mode",
            value="true"
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value="true")
        )
        await db.execute(stmt)
        
        # Update maintenance message
        stmt = insert(PlatformSetting).values(
            key="maintenance_message",
            value=message
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value=message)
        )
        await db.execute(stmt)
        
        await db.commit()

        global _maintenance_cache
        _maintenance_cache = None  # Invalidate cache so next request re-reads DB

        logger.info(f"Maintenance mode enabled by {admin_email or 'system'}")
        return True

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to enable maintenance mode: {e}", exc_info=True)
        return False


async def disable_maintenance_mode(
    db: AsyncSession,
    admin_email: Optional[str] = None
) -> bool:
    """
    Disable maintenance mode
    
    Args:
        db: Database session
        admin_email: Admin email for verification
    
    Returns:
        True if disabled successfully
    """
    try:
        # Verify admin access if email provided
        if admin_email and admin_email.lower() != settings.SUPER_ADMIN_EMAIL.lower():
            raise ValueError("Unauthorized: Only super admin can disable maintenance mode")
        
        # Disable maintenance mode
        from sqlalchemy.dialects.postgresql import insert
        
        stmt = insert(PlatformSetting).values(
            key="maintenance_mode",
            value="false"
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value="false")
        )
        await db.execute(stmt)
        
        await db.commit()

        global _maintenance_cache
        _maintenance_cache = None  # Invalidate cache

        logger.info(f"Maintenance mode disabled by {admin_email or 'system'}")
        return True

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to disable maintenance mode: {e}", exc_info=True)
        return False


async def get_maintenance_status() -> dict:
    """Get current maintenance mode status"""
    try:
        is_maintenance, message = await maintenance_mode.is_maintenance_mode()

        return {
            "maintenance_mode": is_maintenance,
            "message": message,
            "admin_email": settings.SUPER_ADMIN_EMAIL,
            "allowed_endpoints": maintenance_mode.maintenance_endpoints
        }

    except Exception as e:
        return {
            "maintenance_mode": False,
            "message": None,
            "error": str(e)
        }


# ─── Maintenance Mode Decorator ───────────────────────────────────────────────

def require_admin_or_maintenance_bypass(func):
    """
    Decorator to require admin access or bypass maintenance mode
    
    Args:
        func: Function to decorate
    
    Returns:
        Decorated function
    """
    async def wrapper(*args, **kwargs):
        # This decorator would be used on specific endpoints
        # that need admin access during maintenance mode
        # Implementation would depend on the specific endpoint structure
        return await func(*args, **kwargs)
    
    return wrapper


# ─── Emergency Maintenance Functions ──────────────────────────────────────────

async def emergency_maintenance_enable(
    db: AsyncSession,
    reason: str = "Emergency maintenance"
) -> bool:
    """
    Enable emergency maintenance mode (bypasses admin check)
    
    Args:
        db: Database session
        reason: Reason for emergency maintenance
    
    Returns:
        True if enabled successfully
    """
    emergency_message = f"System is temporarily unavailable due to {reason}. We apologize for the inconvenience."
    
    return await enable_maintenance_mode(db, emergency_message)


def is_maintenance_bypass_token(token: str) -> bool:
    """
    Check if token allows maintenance mode bypass
    
    Args:
        token: Bypass token
    
    Returns:
        True if valid bypass token
    """
    # This could be used for emergency access
    # In production, this should be a secure, time-limited token
    bypass_token = getattr(settings, 'MAINTENANCE_BYPASS_TOKEN', None)
    
    if not bypass_token:
        return False
    
    return token == bypass_token