"""
Webhook Security Service
HMAC verification and timing-safe comparison utilities for webhook authentication
"""
import hmac
import hashlib
import secrets
from typing import Optional

from app.config import settings


class WebhookSecurityError(Exception):
    """Base exception for webhook security errors"""
    pass


class WebhookSecurity:
    """
    Webhook security utilities for verifying signatures from different platforms
    Uses timing-safe comparison to prevent timing attacks
    """
    
    @staticmethod
    def verify_telegram_secret(received_token: str) -> bool:
        """
        Verify Telegram webhook secret token
        Uses timing-safe comparison to prevent timing attacks
        """
        if not settings.TELEGRAM_SECRET_TOKEN:
            raise WebhookSecurityError("TELEGRAM_SECRET_TOKEN not configured")
        
        expected_token = settings.TELEGRAM_SECRET_TOKEN
        return secrets.compare_digest(received_token, expected_token)
    
    @staticmethod
    def verify_meta_signature(payload: bytes, signature: str, app_secret: str) -> bool:
        """
        Verify Meta (WhatsApp/Instagram) webhook signature
        Uses HMAC-SHA256 with timing-safe comparison
        
        Args:
            payload: Raw request body bytes
            signature: X-Hub-Signature-256 header value (format: "sha256=<hash>")
            app_secret: App secret for the specific platform
        """
        if not app_secret:
            raise WebhookSecurityError("App secret not configured")
        
        # Remove 'sha256=' prefix if present
        if signature.startswith('sha256='):
            signature = signature[7:]
        
        # Calculate expected signature
        expected_signature = hmac.new(
            app_secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Use timing-safe comparison
        return secrets.compare_digest(signature, expected_signature)
    
    @staticmethod
    def verify_whatsapp_signature(payload: bytes, signature: str) -> bool:
        """
        Verify WhatsApp webhook signature using WhatsApp app secret
        """
        return WebhookSecurity.verify_meta_signature(
            payload, 
            signature, 
            settings.WHATSAPP_APP_SECRET
        )
    
    @staticmethod
    def verify_instagram_signature(payload: bytes, signature: str) -> bool:
        """
        Verify Instagram webhook signature using Instagram app secret
        """
        return WebhookSecurity.verify_meta_signature(
            payload, 
            signature, 
            settings.INSTAGRAM_APP_SECRET
        )
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """
        Generate a cryptographically secure random token
        Used for session tokens, invitation tokens, etc.
        """
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def verify_process_secret(received_secret: str) -> bool:
        """
        Verify internal process secret for API calls
        Uses timing-safe comparison
        """
        if not settings.PROCESS_SECRET:
            raise WebhookSecurityError("PROCESS_SECRET not configured")
        
        return secrets.compare_digest(received_secret, settings.PROCESS_SECRET)


# ─── Convenience Functions ────────────────────────────────────────────────────

def verify_webhook_signature(
    platform: str, 
    payload: bytes, 
    signature: Optional[str] = None,
    token: Optional[str] = None
) -> bool:
    """
    Unified webhook signature verification for all platforms
    
    Args:
        platform: Platform name ('telegram', 'whatsapp', 'instagram')
        payload: Raw request body bytes
        signature: Signature header (for Meta platforms)
        token: Secret token (for Telegram)
    
    Returns:
        True if signature is valid, False otherwise
    
    Raises:
        WebhookSecurityError: If configuration is missing or invalid
    """
    try:
        if platform == 'telegram':
            if not token:
                return False
            return WebhookSecurity.verify_telegram_secret(token)
        
        elif platform == 'whatsapp':
            if not signature:
                return False
            return WebhookSecurity.verify_whatsapp_signature(payload, signature)
        
        elif platform == 'instagram':
            if not signature:
                return False
            return WebhookSecurity.verify_instagram_signature(payload, signature)
        
        else:
            raise WebhookSecurityError(f"Unknown platform: {platform}")
    
    except WebhookSecurityError:
        raise
    except Exception as e:
        raise WebhookSecurityError(f"Signature verification failed: {str(e)}")


def generate_invitation_token() -> str:
    """Generate secure token for agent invitations (7-day expiration)"""
    return WebhookSecurity.generate_secure_token(32)


def generate_session_token() -> str:
    """Generate secure token for WebChat sessions"""
    return WebhookSecurity.generate_secure_token(24)