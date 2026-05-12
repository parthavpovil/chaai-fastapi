"""
Authentication Routes
User registration, login, and authentication endpoints
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
import secrets
import string
import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pydantic import BaseModel

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.agent import Agent
from app.models.platform_setting import PlatformSetting
from app.schemas.auth import (
    UserRegistrationRequest, UserLoginRequest, AgentLoginRequest,
    AgentInviteAcceptRequest, AuthResponse, AuthMeResponse, MessageResponse,
    UserResponse, WorkspaceResponse, RegistrationPendingResponse,
    VerifyEmailRequest, ResendEmailVerificationRequest,
    ForgotPasswordRequest, VerifyPasswordResetRequest, ResetPasswordRequest
)
from app.services.auth_service import auth_service
from app.services.refresh_token_service import (
    create_refresh_token, use_refresh_token, revoke_refresh_token,
    revoke_refresh_tokens_for_user
)
from app.middleware.auth_middleware import get_current_user, get_current_workspace, security
from app.utils.slug import generate_unique_slug
from app.services.auth_rate_limit import check_auth_rate_limit
from app.services.email_service import EmailService
from app.services.disposable_email_service import is_disposable_email

router = APIRouter(prefix="/api/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


def _is_super_admin(email: str) -> bool:
    return bool(settings.SUPER_ADMIN_EMAIL) and email.lower() == settings.SUPER_ADMIN_EMAIL.lower()


def _generate_pin(length: int) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


@router.post("/register", response_model=Union[AuthResponse, RegistrationPendingResponse])
async def register_user(
    request: UserRegistrationRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Register new user and create workspace

    Creates a new user account, generates a unique workspace slug,
    creates the workspace, and returns JWT token.
    """
    await check_auth_rate_limit(http_request, request.email, "register")
    try:
        if is_disposable_email(request.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Disposable email addresses are not allowed"
            )

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

        now = datetime.now(timezone.utc)
        is_super_admin = _is_super_admin(request.email)
        verification_pin = None
        verification_expires_at = None
        
        # Create user
        user = User(
            email=request.email,
            hashed_password=hashed_password,
            is_active=True,
            email_verified=is_super_admin
        )

        if not is_super_admin:
            verification_pin = _generate_pin(settings.EMAIL_VERIFICATION_PIN_LENGTH)
            verification_expires_at = now + timedelta(
                minutes=settings.EMAIL_VERIFICATION_PIN_TTL_MINUTES
            )
            user.email_verification_pin_hash = auth_service.hash_pin(verification_pin)
            user.email_verification_expires_at = verification_expires_at
            user.email_verification_last_sent_at = now
            user.email_verification_sent_day = now.date()
            user.email_verification_sent_count = 1
            user.email_verification_attempts = 0

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
        
        if not is_super_admin:
            email_service = EmailService()
            await email_service.send_email_verification_email(
                to=user.email,
                pin=verification_pin,
                expires_in_minutes=settings.EMAIL_VERIFICATION_PIN_TTL_MINUTES,
            )

        await db.commit()

        if not is_super_admin:
            return RegistrationPendingResponse(
                message="Verification required. Check your email for the PIN.",
                email=user.email,
                verification_expires_at=verification_expires_at.isoformat()
            )

        # Issue access + refresh tokens for super admin
        rt_id = await create_refresh_token(
            user_id=str(user.id), email=user.email, role="owner",
            workspace_id=str(workspace.id),
        )
        access_token = auth_service.create_access_token(
            user_id=user.id, email=user.email, role="owner",
            workspace_id=workspace.id, refresh_token_id=rt_id,
        )

        return AuthResponse(
            access_token=access_token,
            refresh_token=rt_id,
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
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    request: VerifyEmailRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Verify email address with a PIN."""
    await check_auth_rate_limit(http_request, request.email, "verify-email")

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification request"
        )

    if user.email_verified:
        return MessageResponse(message="Email already verified")

    if not user.email_verification_pin_hash or not user.email_verification_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification PIN not found"
        )

    if user.email_verification_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification PIN expired"
        )

    if user.email_verification_attempts >= settings.EMAIL_VERIFICATION_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invalid attempts"
        )

    if not auth_service.verify_pin(request.pin, user.email_verification_pin_hash):
        user.email_verification_attempts += 1
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification PIN"
        )

    user.email_verified = True
    user.email_verification_pin_hash = None
    user.email_verification_expires_at = None
    user.email_verification_attempts = 0
    await db.commit()

    return MessageResponse(message="Email verified successfully")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification_email(
    request: ResendEmailVerificationRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Resend email verification PIN."""
    await check_auth_rate_limit(http_request, request.email, "resend-verification")

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification request"
        )

    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already verified"
        )

    now = datetime.now(timezone.utc)
    if user.email_verification_sent_day != now.date():
        user.email_verification_sent_day = now.date()
        user.email_verification_sent_count = 0

    if user.email_verification_sent_count >= settings.EMAIL_VERIFICATION_MAX_DAILY_SENDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily resend limit reached"
        )

    if user.email_verification_last_sent_at:
        elapsed = (now - user.email_verification_last_sent_at).total_seconds()
        if elapsed < settings.EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Please wait before requesting another PIN"
            )

    try:
        pin = _generate_pin(settings.EMAIL_VERIFICATION_PIN_LENGTH)
        user.email_verification_pin_hash = auth_service.hash_pin(pin)
        user.email_verification_expires_at = now + timedelta(
            minutes=settings.EMAIL_VERIFICATION_PIN_TTL_MINUTES
        )
        user.email_verification_last_sent_at = now
        user.email_verification_sent_day = now.date()
        user.email_verification_sent_count += 1
        user.email_verification_attempts = 0

        email_service = EmailService()
        await email_service.send_email_verification_email(
            to=user.email,
            pin=pin,
            expires_in_minutes=settings.EMAIL_VERIFICATION_PIN_TTL_MINUTES,
        )

        await db.commit()
        return MessageResponse(message="Verification PIN resent")
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Send password reset PIN to the user's email."""
    await check_auth_rate_limit(http_request, request.email, "forgot-password")

    generic_message = "If the account exists, a reset PIN has been sent."

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return MessageResponse(message=generic_message)

    now = datetime.now(timezone.utc)
    if user.password_reset_sent_day != now.date():
        user.password_reset_sent_day = now.date()
        user.password_reset_sent_count = 0

    if user.password_reset_sent_count >= settings.PASSWORD_RESET_MAX_DAILY_SENDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily reset PIN limit reached"
        )

    if user.password_reset_last_sent_at:
        elapsed = (now - user.password_reset_last_sent_at).total_seconds()
        if elapsed < settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Please wait before requesting another PIN"
            )

    try:
        pin = _generate_pin(settings.PASSWORD_RESET_PIN_LENGTH)
        user.password_reset_pin_hash = auth_service.hash_pin(pin)
        user.password_reset_expires_at = now + timedelta(
            minutes=settings.PASSWORD_RESET_PIN_TTL_MINUTES
        )
        user.password_reset_last_sent_at = now
        user.password_reset_sent_day = now.date()
        user.password_reset_sent_count += 1
        user.password_reset_attempts = 0

        email_service = EmailService()
        await email_service.send_password_reset_pin_email(
            to=user.email,
            pin=pin,
            expires_in_minutes=settings.PASSWORD_RESET_PIN_TTL_MINUTES,
        )

        await db.commit()
        return MessageResponse(message=generic_message)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/verify-password-reset", response_model=MessageResponse)
async def verify_password_reset(
    request: VerifyPasswordResetRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Verify a password reset PIN."""
    await check_auth_rate_limit(http_request, request.email, "verify-password-reset")

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset request"
        )

    if not user.password_reset_pin_hash or not user.password_reset_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset PIN not found"
        )

    if user.password_reset_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset PIN expired"
        )

    if user.password_reset_attempts >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invalid attempts"
        )

    if not auth_service.verify_pin(request.pin, user.password_reset_pin_hash):
        user.password_reset_attempts += 1
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset PIN"
        )

    return MessageResponse(message="Reset PIN verified")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Reset password using a valid PIN."""
    await check_auth_rate_limit(http_request, request.email, "reset-password")

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset request"
        )

    if not user.password_reset_pin_hash or not user.password_reset_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset PIN not found"
        )

    if user.password_reset_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset PIN expired"
        )

    if user.password_reset_attempts >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invalid attempts"
        )

    if not auth_service.verify_pin(request.pin, user.password_reset_pin_hash):
        user.password_reset_attempts += 1
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset PIN"
        )

    user.hashed_password = auth_service.hash_password(request.new_password)
    user.password_reset_pin_hash = None
    user.password_reset_expires_at = None
    user.password_reset_attempts = 0
    await db.commit()

    try:
        await revoke_refresh_tokens_for_user(str(user.id))
    except Exception:
        logger.warning("Failed to revoke refresh tokens after password reset", exc_info=True)

    return MessageResponse(message="Password updated. Please log in again.")


@router.post("/login", response_model=AuthResponse)
async def login_user(
    request: UserLoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    User login with email and password

    Validates credentials and returns JWT token for workspace owners.
    """
    await check_auth_rate_limit(http_request, request.email, "login")
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

    if not user.email_verified and not _is_super_admin(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Email not verified",
                "code": "email_not_verified"
            }
        )
    
    # Block agent accounts from using the owner login endpoint
    agent_result = await db.execute(
        select(Agent).where(Agent.user_id == user.id, Agent.is_active == True)
    )
    agent_profile = agent_result.scalar_one_or_none()
    if agent_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Looks like you're trying to sign in as an owner, but this account is set up as an agent. Try signing in at the agent login instead.",
                "role": "agent"
            }
        )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Load user's workspace
    result = await db.execute(select(Workspace).where(Workspace.owner_id == user.id))
    workspace = result.scalar_one_or_none()

    role = "superadmin" if _is_super_admin(user.email) else "owner"

    # Issue access + refresh tokens
    rt_id = await create_refresh_token(
        user_id=str(user.id), email=user.email, role=role,
        workspace_id=str(workspace.id) if workspace else None,
    )
    access_token = auth_service.create_access_token(
        user_id=user.id, email=user.email, role=role,
        workspace_id=workspace.id if workspace else None,
        refresh_token_id=rt_id,
    )

    return AuthResponse(
        access_token=access_token,
        refresh_token=rt_id,
        user=UserResponse.model_validate(user),
        workspace=WorkspaceResponse.model_validate(workspace) if workspace else None
    )


@router.post("/agent-login", response_model=AuthResponse)
async def login_agent(
    request: AgentLoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Agent login with email and password

    Validates credentials and returns JWT token for agents.
    """
    await check_auth_rate_limit(http_request, request.email, "agent-login")
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
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.owner_id == user.id)
        )
        owner_workspace = workspace_result.scalar_one_or_none()
        role = "owner" if owner_workspace else None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "No active agent profile found",
                "role": role
            }
        )
    
    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    
    # Issue access + refresh tokens
    rt_id = await create_refresh_token(
        user_id=str(user.id), email=user.email, role="agent",
        workspace_id=str(agent.workspace_id) if agent.workspace_id else None,
    )
    access_token = auth_service.create_access_token(
        user_id=user.id, email=user.email, role="agent",
        workspace_id=agent.workspace_id, refresh_token_id=rt_id,
    )

    return AuthResponse(
        access_token=access_token,
        refresh_token=rt_id,
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
            is_active=True,
            email_verified=True
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
    refresh_token: str


class TokenRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/logout", response_model=MessageResponse)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(get_current_user),
):
    """Logout: revoke the access token JTI and the linked refresh token."""
    token = credentials.credentials
    payload = auth_service.decode_access_token(token)

    if payload:
        jti = payload.get("jti")
        exp = payload.get("exp")
        rt_id = payload.get("rt")

        from app.services.token_blocklist import block_token
        if jti and exp:
            await block_token(jti, exp)
        if rt_id:
            await revoke_refresh_token(rt_id)

    return MessageResponse(message="Logged out successfully")


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(request: TokenRefreshRequest):
    """Exchange a valid refresh token for a new access token + rotated refresh token.

    The old refresh token is deleted atomically on use (rotation). A replayed
    or stolen token returns 401.
    """
    claims = await use_refresh_token(request.refresh_token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    workspace_id_str = claims.get("workspace_id")
    workspace_id = UUID(workspace_id_str) if workspace_id_str else None

    new_rt_id = await create_refresh_token(
        user_id=claims["user_id"],
        email=claims["email"],
        role=claims["role"],
        workspace_id=workspace_id_str,
    )
    new_access_token = auth_service.create_access_token(
        user_id=UUID(claims["user_id"]),
        email=claims["email"],
        role=claims["role"],
        workspace_id=workspace_id,
        refresh_token_id=new_rt_id,
    )
    return TokenRefreshResponse(access_token=new_access_token, refresh_token=new_rt_id)