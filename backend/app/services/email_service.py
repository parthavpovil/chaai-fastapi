"""
Email Service using Resend API
Handles transactional emails for the application
"""
import httpx
from typing import Optional, List, Dict, Any
from app.config import settings

# Deployment trigger


class EmailService:
    """Service for sending emails via Resend API"""
    
    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        self.base_url = "https://api.resend.com"
    
    async def send_email(
        self,
        to: str | List[str],
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        tags: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Send an email via Resend API
        
        Args:
            to: Recipient email address(es)
            subject: Email subject
            html: HTML email body
            text: Plain text email body (optional)
            from_email: Sender email (defaults to RESEND_FROM_EMAIL)
            reply_to: Reply-to email address
            cc: CC recipients
            bcc: BCC recipients
            tags: Email tags for tracking
            
        Returns:
            Response from Resend API containing email ID
            
        Raises:
            httpx.HTTPStatusError: If the API request fails
        """
        if not self.api_key:
            raise ValueError("RESEND_API_KEY not configured")
        
        # Prepare payload
        payload = {
            "from": from_email or self.from_email,
            "to": [to] if isinstance(to, str) else to,
            "subject": subject,
            "html": html,
        }
        
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if tags:
            payload["tags"] = tags
        
        # Send request
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/emails",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
    
    async def send_password_reset_email(
        self,
        to: str,
        reset_token: str,
        user_name: str,
    ) -> Dict[str, Any]:
        """Send password reset email"""
        reset_url = f"{settings.APP_URL}/reset-password?token={reset_token}"
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">Password Reset Request</h2>
                <p>Hi {user_name},</p>
                <p>We received a request to reset your password. Click the button below to create a new password:</p>
                <div style="margin: 30px 0;">
                    <a href="{reset_url}" 
                       style="background-color: #2563eb; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 6px; display: inline-block;">
                        Reset Password
                    </a>
                </div>
                <p>Or copy and paste this link into your browser:</p>
                <p style="color: #666; word-break: break-all;">{reset_url}</p>
                <p style="margin-top: 30px; color: #666; font-size: 14px;">
                    This link will expire in 1 hour. If you didn't request a password reset, 
                    you can safely ignore this email.
                </p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #999; font-size: 12px;">
                    ChatSaaS - AI-Powered Customer Support Platform
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(
            to=to,
            subject="Reset Your Password",
            html=html,
            tags=[{"name": "category", "value": "password_reset"}],
        )
    
    async def send_welcome_email(
        self,
        to: str,
        user_name: str,
        workspace_name: str,
    ) -> Dict[str, Any]:
        """Send welcome email to new users"""
        dashboard_url = f"{settings.APP_URL}/dashboard"
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">Welcome to ChatSaaS! 🎉</h2>
                <p>Hi {user_name},</p>
                <p>Welcome to your new workspace: <strong>{workspace_name}</strong></p>
                <p>You're all set to start building amazing customer support experiences with AI.</p>
                <div style="margin: 30px 0;">
                    <a href="{dashboard_url}" 
                       style="background-color: #2563eb; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 6px; display: inline-block;">
                        Go to Dashboard
                    </a>
                </div>
                <h3 style="color: #333; margin-top: 30px;">Quick Start Guide:</h3>
                <ol style="color: #666;">
                    <li>Connect your first channel (WhatsApp, Telegram, or Instagram)</li>
                    <li>Upload knowledge base documents</li>
                    <li>Configure your AI agent settings</li>
                    <li>Start receiving and responding to messages</li>
                </ol>
                <p style="margin-top: 30px;">
                    Need help? Check out our 
                    <a href="{settings.APP_URL}/docs" style="color: #2563eb;">documentation</a> 
                    or reach out to our support team.
                </p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #999; font-size: 12px;">
                    ChatSaaS - AI-Powered Customer Support Platform
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(
            to=to,
            subject=f"Welcome to {workspace_name}!",
            html=html,
            tags=[{"name": "category", "value": "welcome"}],
        )
    
    async def send_tier_limit_alert(
        self,
        to: str,
        user_name: str,
        limit_type: str,
        current_usage: int,
        limit: int,
        tier: str,
    ) -> Dict[str, Any]:
        """Send alert when approaching or exceeding tier limits"""
        percentage = (current_usage / limit) * 100
        upgrade_url = f"{settings.APP_URL}/settings/billing"
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #dc2626;">⚠️ Usage Limit Alert</h2>
                <p>Hi {user_name},</p>
                <p>You're approaching your <strong>{tier}</strong> plan limit for <strong>{limit_type}</strong>.</p>
                <div style="background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 15px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Current Usage:</strong> {current_usage} / {limit} ({percentage:.1f}%)</p>
                </div>
                <p>To continue without interruption, consider upgrading your plan:</p>
                <div style="margin: 30px 0;">
                    <a href="{upgrade_url}" 
                       style="background-color: #2563eb; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 6px; display: inline-block;">
                        Upgrade Plan
                    </a>
                </div>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #999; font-size: 12px;">
                    ChatSaaS - AI-Powered Customer Support Platform
                </p>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(
            to=to,
            subject=f"Usage Alert: {limit_type} limit approaching",
            html=html,
            tags=[{"name": "category", "value": "tier_limit_alert"}],
        )


    async def send_escalation_alert(
        self,
        to_email: str,
        workspace_id: str,
        conversation_id: str,
        escalation_reason: str,
        priority: str = "medium",
        classification_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send escalation alert email to workspace owner"""
        priority_colors = {"high": "#dc2626", "medium": "#d97706", "low": "#2563eb"}
        color = priority_colors.get(priority, "#d97706")

        classification_html = ""
        if classification_data:
            classification_html = f"<p><strong>Classification:</strong> {classification_data}</p>"

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: {color};">Escalation Alert — {priority.upper()} Priority</h2>
                <p>A conversation requires your attention.</p>
                <div style="background-color: #fef9ec; border-left: 4px solid {color}; padding: 15px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Reason:</strong> {escalation_reason}</p>
                    <p style="margin: 8px 0 0;"><strong>Conversation ID:</strong> {conversation_id}</p>
                    <p style="margin: 8px 0 0;"><strong>Workspace ID:</strong> {workspace_id}</p>
                </div>
                {classification_html}
                <div style="margin: 30px 0;">
                    <a href="{settings.APP_URL}/conversations/{conversation_id}"
                       style="background-color: {color}; color: white; padding: 12px 24px;
                              text-decoration: none; border-radius: 6px; display: inline-block;">
                        View Conversation
                    </a>
                </div>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #999; font-size: 12px;">ChatSaaS - AI-Powered Customer Support Platform</p>
            </div>
        </body>
        </html>
        """

        try:
            await self.send_email(
                to=to_email,
                subject=f"[{priority.upper()}] Escalation Alert — Action Required",
                html=html,
                tags=[{"name": "category", "value": "escalation_alert"}],
            )
            return True
        except Exception:
            return False


# Global email service instance
email_service = EmailService()
