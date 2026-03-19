"""
Maintenance Mode Middleware
Handles maintenance mode checking and admin access control
"""
from typing import Callable, Optional
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.platform_setting import PlatformSetting
from app.services.auth_service import AuthService
from app.config import settings


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
    
    async def is_maintenance_mode(self, db: AsyncSession) -> tuple[bool, Optional[str]]:
        """
        Check if system is in maintenance mode
        
        Args:
            db: Database session
        
        Returns:
            Tuple of (is_maintenance, maintenance_message)
        """
        try:
            # Get maintenance mode setting
            result = await db.execute(
                select(PlatformSetting.value)
                .where(PlatformSetting.key == "maintenance_mode")
            )
            maintenance_setting = result.scalar_one_or_none()
            
            if maintenance_setting == "true":
                # Get maintenance message
                message_result = await db.execute(
                    select(PlatformSetting.value)
                    .where(PlatformSetting.key == "maintenance_message")
                )
                maintenance_message = message_result.scalar_one_or_none()
                return True, maintenance_message or "System is currently under maintenance."
            
            return False, None
            
        except Exception as e:
            print(f"Error checking maintenance mode: {e}")
            # Fail safe - assume not in maintenance mode
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


async def maintenance_mode_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware to check maintenance mode and block non-admin requests
    
    Args:
        request: FastAPI request
        call_next: Next middleware/endpoint
    
    Returns:
        Response or maintenance mode error
    """
    try:
        # Skip maintenance check for allowed endpoints
        if maintenance_mode.is_allowed_endpoint(request.url.path):
            return await call_next(request)
        
        # Get database session
        db = None
        try:
            db = await anext(get_db())
            
            # Check if system is in maintenance mode
            is_maintenance, maintenance_message = await maintenance_mode.is_maintenance_mode(db)
            
            if is_maintenance:
                # Check if user is admin
                if not maintenance_mode.is_admin_user(request):
                    return await maintenance_mode.create_maintenance_response(
                        maintenance_message, 
                        request.url.path
                    )
                
                # Admin user - add maintenance header but allow request
                response = await call_next(request)
                response.headers["X-Maintenance-Mode"] = "true"
                response.headers["X-Admin-Access"] = "true"
                return response
            
            # Not in maintenance mode - proceed normally
            return await call_next(request)
            
        finally:
            if db:
                await db.close()
                
    except Exception as e:
        print(f"Maintenance middleware error: {e}")
        # On error, allow request to proceed
        return await call_next(request)


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
        
        print(f"Maintenance mode enabled by {admin_email or 'system'}")
        return True
        
    except Exception as e:
        await db.rollback()
        print(f"Failed to enable maintenance mode: {e}")
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
        
        print(f"Maintenance mode disabled by {admin_email or 'system'}")
        return True
        
    except Exception as e:
        await db.rollback()
        print(f"Failed to disable maintenance mode: {e}")
        return False


async def get_maintenance_status(db: AsyncSession) -> dict:
    """
    Get current maintenance mode status
    
    Args:
        db: Database session
    
    Returns:
        Maintenance status information
    """
    try:
        is_maintenance, message = await maintenance_mode.is_maintenance_mode(db)
        
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