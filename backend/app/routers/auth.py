"""
Authentication Routes
User registration, login, and authentication endpoints
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pydantic import BaseModel

from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.platform_setting import PlatformSetting
from app.schemas.auth import (
    UserRegistrationRequest, UserLoginRequest, AgentLoginRequest,
    AgentInviteAcceptRequest, AuthResponse, AuthMeResponse, MessageResponse,
    UserResponse, WorkspaceResponse
)
from app.services.auth_service import auth_service
from app.middleware.auth_middleware import get_current_user, get_current_workspace, security
from app.utils.slug import generate_unique_slug

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/register", response_model=AuthResponse)
async def register_user(
    request: UserRegistrationRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Register new user and create workspace
    
    Creates a new user account, generates a unique workspace slug,
    creates the workspace, and returns JWT token.
    """
    try:
        # Check if email is already registered
        result = await db.execute(select(User).where(User.email == request.email))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Hash password
        hashed_password = auth_service.hash_password(request.password)
        
        # Create user
        user = User(
            email=request.email,
            hashed_password=hashed_password,
            is_active=True
        )
        db.add(user)
        await db.flush()  # Get user ID
        
        # Generate unique workspace slug
        workspace_slug = await generate_unique_slug(request.business_name, db)
        
        # Create workspace
        workspace = Workspace(
            owner_id=user.id,
            name=request.business_name,
            slug=workspace_slug,
            tier="free"
        )
        db.add(workspace)
        
        # Create default platform settings if this is the first user
        result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "maintenance_mode"))
        if not result.scalar_one_or_none():
            default_settings = [
                PlatformSetting(key="maintenance_mode", value="false"),
                PlatformSetting(key="maintenance_message", value="System is under maintenance. Please try again later.")
            ]
            for setting in default_settings:
                db.add(setting)
        
        await db.commit()
        
        # Generate JWT token
        access_token = auth_service.create_access_token(
            user_id=user.id,
            email=user.email,
            role="owner",
            workspace_id=workspace.id
        )
        
        return AuthResponse(
            access_token=access_token,
            user=UserResponse.model_validate(user),
            workspace=WorkspaceResponse.model_validate(workspace)
        )
        
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/login", response_model=AuthResponse)
async def login_user(
    request: UserLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    User login with email and password
    
    Validates credentials and returns JWT token for workspace owners.
    """
    # Find user by email
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Verify password
    if not auth_service.verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive"
        )
    
    # Block agent accounts from using the owner login endpoint
    agent_result = await db.execute(
        select(Agent).where(Agent.user_id == user.id, Agent.is_active == True)
    )
    agent_profile = agent_result.scalar_one_or_none()
    if agent_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Looks like you're trying to sign in as an owner, but this account is set up as an agent. Try signing in at the agent login instead."
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Load user's workspace
    result = await db.execute(select(Workspace).where(Workspace.owner_id == user.id))
    workspace = result.scalar_one_or_none()
    
    # Generate JWT token
    access_token = auth_service.create_access_token(
        user_id=user.id,
        email=user.email,
        role="owner",
        workspace_id=workspace.id if workspace else None
    )
    
    return AuthResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
        workspace=WorkspaceResponse.model_validate(workspace) if workspace else None
    )


@router.post("/agent-login", response_model=AuthResponse)
async def login_agent(
    request: AgentLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Agent login with email and password
    
    Validates credentials and returns JWT token for agents.
    """
    # Find user by email
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Verify password
    if not auth_service.verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive"
        )
    
    # Find agent record linked to this user
    result = await db.execute(
        select(Agent).where(
            Agent.user_id == user.id,
            Agent.is_active == True
        )
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active agent profile found"
        )
    
    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    
    # Generate JWT token with agent role and workspace
    access_token = auth_service.create_access_token(
        user_id=user.id,
        email=user.email,
        role="agent",
        workspace_id=agent.workspace_id
    )
    
    return AuthResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
        workspace=None  # Agents don't get workspace details in response
    )


@router.post("/accept-invite", response_model=MessageResponse)
async def accept_agent_invitation(
    request: AgentInviteAcceptRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Accept agent invitation and create account
    
    Creates user account for invited agent and links to agent record.
    """
    # Find agent by invitation token
    result = await db.execute(
        select(Agent).where(Agent.invitation_token == request.token)
    )
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token"
        )
    
    # Check if invitation is expired
    if agent.invitation_expires_at and agent.invitation_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has expired"
        )
    
    # Check if invitation already accepted
    if agent.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation already accepted"
        )
    
    try:
        # Hash password
        hashed_password = auth_service.hash_password(request.password)
        
        # Create user account
        user = User(
            email=agent.email,
            hashed_password=hashed_password,
            is_active=True
        )
        db.add(user)
        await db.flush()  # Get user ID
        
        # Link user to agent record
        agent.user_id = user.id
        agent.is_active = True
        agent.invitation_token = None
        agent.invitation_accepted_at = datetime.now(timezone.utc)
        
        await db.commit()
        
        return MessageResponse(message="Account created. You can now log in.")
        
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )


@router.get("/me", response_model=AuthMeResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user information
    
    Returns user details and workspace information if available.
    """
    # Try to get workspace (for owners) or agent workspace (for agents)
    workspace = None
    
    # Check if user is workspace owner
    result = await db.execute(select(Workspace).where(Workspace.owner_id == current_user.id))
    workspace = result.scalar_one_or_none()
    
    # If not owner, check if user is an agent
    if not workspace:
        result = await db.execute(
            select(Agent, Workspace).join(Workspace).where(
                Agent.user_id == current_user.id,
                Agent.is_active == True
            )
        )
        agent_workspace = result.first()
        if agent_workspace:
            workspace = agent_workspace.Workspace
    
    return AuthMeResponse(
        user=UserResponse.model_validate(current_user),
        workspace=WorkspaceResponse.model_validate(workspace) if workspace else None
    )


class TokenRefreshRequest(BaseModel):
    token: str


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/logout", response_model=MessageResponse)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(get_current_user),
):
    """
    Logout the current user by revoking their JWT token.

    Adds the token's JTI to a Redis blocklist until the token's natural
    expiry time, so it is rejected on all subsequent requests.
    """
    token = credentials.credentials
    payload = auth_service.decode_access_token(token)

    if payload:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            from app.services.token_blocklist import block_token
            await block_token(jti, exp)

    return MessageResponse(message="Logged out successfully")


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(request: TokenRefreshRequest):
    """
    Silently refresh a JWT token before it expires.

    Accepts a valid (non-expired) token and returns a new token with a fresh
    expiry. Frontend should call this proactively (e.g. 5 minutes before exp)
    to avoid mid-session logouts.
    """
    payload = auth_service.decode_access_token(request.token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    workspace_id_str = payload.get("workspace_id")
    workspace_id = UUID(workspace_id_str) if workspace_id_str else None

    new_token = auth_service.create_access_token(
        user_id=UUID(payload["sub"]),
        email=payload["email"],
        role=payload["role"],
        workspace_id=workspace_id,
    )
    return TokenRefreshResponse(access_token=new_token)