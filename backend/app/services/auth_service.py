"""
Authentication Service
JWT token generation, validation, and password hashing
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from jose import JWTError, jwt
import bcrypt

from app.config import settings


class AuthService:
    """Authentication service for JWT tokens and password management"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt with proper salt rounds
        
        Note: Bcrypt has a 72-byte limit. Passwords are automatically truncated.
        """
        # Bcrypt automatically handles truncation to 72 bytes
        password_bytes = password.encode('utf-8')
        # Truncate to 72 bytes if needed
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash
        
        Note: Bcrypt has a 72-byte limit. Passwords are automatically truncated.
        """
        password_bytes = plain_password.encode('utf-8')
        # Truncate to 72 bytes if needed
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    
    @staticmethod
    def create_access_token(
        user_id: UUID,
        email: str,
        role: str,
        workspace_id: Optional[UUID] = None,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create JWT access token with user claims
        
        Args:
            user_id: User UUID
            email: User email address
            role: User role (owner | agent)
            workspace_id: Workspace UUID (null for agents until accepted)
            expires_delta: Custom expiration time
            
        Returns:
            JWT token string
        """
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
        
        # Create token payload
        to_encode = {
            "sub": str(user_id),  # Subject (user ID)
            "email": email,
            "role": role,
            "workspace_id": str(workspace_id) if workspace_id else None,
            "exp": expire,
            "iat": datetime.now(timezone.utc),  # Issued at
            "jti": str(uuid4()),               # Unique token ID (used for blocklist on logout)
        }
        
        # Encode JWT token
        encoded_jwt = jwt.encode(
            to_encode, 
            settings.JWT_SECRET_KEY, 
            algorithm=settings.JWT_ALGORITHM
        )
        
        return encoded_jwt
    
    @staticmethod
    def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
        """
        Decode and validate JWT access token
        
        Args:
            token: JWT token string
            
        Returns:
            Token payload dict or None if invalid
        """
        try:
            payload = jwt.decode(
                token, 
                settings.JWT_SECRET_KEY, 
                algorithms=[settings.JWT_ALGORITHM]
            )
            
            # Validate required fields
            user_id = payload.get("sub")
            email = payload.get("email")
            role = payload.get("role")
            
            if not all([user_id, email, role]):
                return None
                
            return payload
            
        except JWTError:
            return None
    
    @staticmethod
    def get_user_id_from_token(token: str) -> Optional[UUID]:
        """Extract user ID from JWT token"""
        payload = AuthService.decode_access_token(token)
        if payload:
            try:
                return UUID(payload["sub"])
            except (ValueError, KeyError):
                return None
        return None
    
    @staticmethod
    def get_workspace_id_from_token(token: str) -> Optional[UUID]:
        """Extract workspace ID from JWT token"""
        payload = AuthService.decode_access_token(token)
        if payload and payload.get("workspace_id"):
            try:
                return UUID(payload["workspace_id"])
            except (ValueError, KeyError):
                return None
        return None
    
    @staticmethod
    def is_token_expired(token: str) -> bool:
        """Check if JWT token is expired"""
        payload = AuthService.decode_access_token(token)
        if not payload:
            return True
            
        exp = payload.get("exp")
        if not exp:
            return True
            
        return datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc)


# Global auth service instance
auth_service = AuthService()