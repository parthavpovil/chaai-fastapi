"""
Authentication Schemas
Pydantic models for authentication requests and responses
"""
import re
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegistrationRequest(BaseModel):
    """User registration request schema"""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (minimum 8 characters)")
    business_name: str = Field(..., min_length=1, max_length=100, description="Business name for workspace")

    @field_validator("business_name")
    @classmethod
    def sanitize_business_name(cls, v: str) -> str:
        return re.sub(r"<[^>]+>", "", v).strip()


class UserLoginRequest(BaseModel):
    """User login request schema"""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class AgentLoginRequest(BaseModel):
    """Agent login request schema"""
    email: EmailStr = Field(..., description="Agent email address")
    password: str = Field(..., description="Agent password")


class AgentInviteAcceptRequest(BaseModel):
    """Agent invitation acceptance request schema"""
    token: str = Field(..., description="Invitation token")
    password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")


class UserResponse(BaseModel):
    """User response schema"""
    id: UUID
    email: str
    email_verified: bool
    
    class Config:
        from_attributes = True


class WorkspaceResponse(BaseModel):
    """Workspace response schema"""
    id: UUID
    name: str
    slug: str
    tier: str
    
    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    """Authentication response schema"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
    workspace: Optional[WorkspaceResponse] = None


class RegistrationPendingResponse(BaseModel):
    """Registration pending verification response"""
    message: str
    email: str
    verification_expires_at: str


class VerifyEmailRequest(BaseModel):
    """Email verification request schema"""
    email: EmailStr = Field(..., description="User email address")
    pin: str = Field(..., min_length=4, max_length=12, description="Verification PIN")


class ResendEmailVerificationRequest(BaseModel):
    """Resend verification email request schema"""
    email: EmailStr = Field(..., description="User email address")


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema"""
    email: EmailStr = Field(..., description="User email address")


class VerifyPasswordResetRequest(BaseModel):
    """Verify password reset PIN request schema"""
    email: EmailStr = Field(..., description="User email address")
    pin: str = Field(..., min_length=4, max_length=12, description="Password reset PIN")


class ResetPasswordRequest(BaseModel):
    """Reset password request schema"""
    email: EmailStr = Field(..., description="User email address")
    pin: str = Field(..., min_length=4, max_length=12, description="Password reset PIN")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")


class AuthMeResponse(BaseModel):
    """Current user info response schema"""
    user: UserResponse
    workspace: Optional[WorkspaceResponse] = None


class MessageResponse(BaseModel):
    """Simple message response schema"""
    message: str


class ErrorResponse(BaseModel):
    """Structured error response schema"""
    error_code: str = Field(..., description="Machine-readable error code")
    detail: str = Field(..., description="Human-readable error message")
    error_type: str = Field(
        ..., 
        description="Error classification: 'validation_error', 'business_logic_error', 'server_error', 'rate_limit'",
        regex="^(validation_error|business_logic_error|server_error|rate_limit)$"
    )
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp when error occurred")
    request_id: Optional[str] = Field(None, description="Request tracking ID for debugging")