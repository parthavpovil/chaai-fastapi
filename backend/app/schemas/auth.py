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
    token_type: str = "bearer"
    user: UserResponse
    workspace: Optional[WorkspaceResponse] = None


class AuthMeResponse(BaseModel):
    """Current user info response schema"""
    user: UserResponse
    workspace: Optional[WorkspaceResponse] = None


class MessageResponse(BaseModel):
    """Simple message response schema"""
    message: str