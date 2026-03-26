"""
Authentication Middleware and Dependencies
JWT token validation and user/workspace loading
"""
from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.services.auth_service import auth_service

# HTTP Bearer token scheme
security = HTTPBearer()


class AuthenticationError(HTTPException):
    """Custom authentication error"""
    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class PermissionError(HTTPException):
    """Custom permission error"""
    def __init__(self, detail: str = "Not enough permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user.
    Accepts both JWT tokens and API keys (csk_* prefix).
    """
    token = credentials.credentials

    # ── API Key path ────────────────────────────────────────────────────────
    if token.startswith("csk_"):
        from app.services.api_key_service import validate_api_key
        result = await validate_api_key(token, db)
        if not result:
            raise AuthenticationError("Invalid or expired API key")
        api_key, workspace = result
        # Return the workspace owner as the "current user" for API key requests
        owner_result = await db.execute(select(User).where(User.id == workspace.owner_id))
        user = owner_result.scalar_one_or_none()
        if not user or not user.is_active:
            raise AuthenticationError("Workspace owner account is inactive")
        return user

    # ── JWT path ─────────────────────────────────────────────────────────────
    payload = auth_service.decode_access_token(token)
    if not payload:
        raise AuthenticationError("Invalid token")

    # Reject tokens that have been explicitly logged out
    jti = payload.get("jti")
    if jti:
        from app.services.token_blocklist import is_blocked
        if await is_blocked(jti):
            raise AuthenticationError("Token has been revoked")

    try:
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError):
        raise AuthenticationError("Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise AuthenticationError("User not found")

    if not user.is_active:
        raise AuthenticationError("Inactive user")

    return user


async def get_current_workspace(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Workspace:
    """
    Dependency to get current user's workspace
    Used for workspace owner endpoints
    """
    # Load workspace owned by current user
    result = await db.execute(
        select(Workspace).where(Workspace.owner_id == current_user.id)
    )
    workspace = result.scalar_one_or_none()
    
    if not workspace:
        raise PermissionError("No workspace found for user")
    
    return workspace


async def get_current_agent(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Agent:
    """
    Dependency to get current user's agent profile
    Used for agent-specific endpoints
    """
    # Load agent profile for current user
    result = await db.execute(
        select(Agent).where(
            Agent.user_id == current_user.id,
            Agent.is_active == True
        )
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise PermissionError("No active agent profile found")
    
    return agent


async def get_workspace_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Workspace:
    """
    Dependency to get workspace from JWT token
    Used for WebSocket connections and agent endpoints
    """
    token = credentials.credentials
    
    # Get workspace ID from token
    workspace_id = auth_service.get_workspace_id_from_token(token)
    if not workspace_id:
        raise AuthenticationError("No workspace in token")
    
    # Load workspace from database
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    
    if not workspace:
        raise AuthenticationError("Workspace not found")
    
    return workspace


def require_role(required_role: str):
    """
    Dependency factory to require specific user role
    
    Args:
        required_role: Required role (owner | agent)
    
    Returns:
        Dependency function
    """
    async def role_checker(
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> None:
        token = credentials.credentials
        payload = auth_service.decode_access_token(token)
        
        if not payload:
            raise AuthenticationError("Invalid token")
        
        user_role = payload.get("role")
        if user_role != required_role:
            raise PermissionError(f"Role '{required_role}' required")
    
    return role_checker


def require_workspace_access(workspace_id: UUID):
    """
    Dependency factory to require access to specific workspace
    
    Args:
        workspace_id: Required workspace UUID
    
    Returns:
        Dependency function
    """
    async def workspace_checker(
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ) -> None:
        token = credentials.credentials
        token_workspace_id = auth_service.get_workspace_id_from_token(token)
        
        if not token_workspace_id or token_workspace_id != workspace_id:
            raise PermissionError("Access to workspace denied")
    
    return workspace_checker


# Optional token dependency for public endpoints that can use auth
async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Optional dependency to get current user if token is provided
    Used for endpoints that work with or without authentication
    """
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None