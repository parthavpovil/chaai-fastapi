"""
Email Service with Resend Integration
Handles escalation alerts and agent invitation emails
"""
import aiohttp
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


class EmailError(Exception):
    """Base exception for email service errors"""
    pass


class EmailService:
    """
    Email service using Resend API
    Handles escalation alerts and agent invitation emails
    """
    
    def __init__(self):
        self.api_url = "https://api.resend.com"
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        self.timeout = aiohttp.ClientTimeout(total=30)
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send email via Resend API
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text content (optional)
            reply_to: Reply-to email address (optional)
        
        Returns:
            Resend API response
        
        Raises:
            EmailError: If email sending fails
        """
        if not self.api_key:
            raise EmailError("RESEND_API_KEY not configured")
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "from": self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content
            }
            
            if text_content:
                payload["text"] = text_content
            
            if reply_to:
                payload["reply_to"] = [reply_to]
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.api_url}/emails",
                    headers=headers,
                    json=payload
                ) as response:
                    response_data = await response.json()
                    
                    if response.status != 200:
                        error_msg = response_data.get("message", f"HTTP {response.status}")
                        raise EmailError(f"Resend API error: {error_msg}")
                    
                    return response_data
                    
        except aiohttp.ClientError as e:
            raise EmailError(f"Network error sending email: {str(e)}")
        except Exception as e:
            if isinstance(e, EmailError):
                raise
            raise EmailError(f"Email sending failed: {str(e)}")
    
    async def send_escalation_alert(
        self,
        workspace_owner_email: str,
        workspace_name: str,
        conversation_id: str,
        escalation_reason: str,
        priority: str = "medium",
        contact_name: str = "Unknown",
        channel_type: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Send escalation alert email to workspace owner
        
        Args:
            workspace_owner_email: Owner email address
            workspace_name: Workspace name
            conversation_id: Conversation ID
            escalation_reason: Reason for escalation
            priority: Priority level
            contact_name: Customer contact name
            channel_type: Channel type
        
        Returns:
            Email sending result
        """
        subject = f"🚨 Customer Escalation Alert - {workspace_name}"
        
        # Priority emoji and styling
        priority_info = {
            "high": {"emoji": "🔴", "color": "#dc2626", "label": "High Priority"},
            "medium": {"emoji": "🟡", "color": "#ea580c", "label": "Medium Priority"},
            "low": {"emoji": "🟢", "color": "#16a34a", "label": "Low Priority"}
        }
        
        priority_data = priority_info.get(priority, priority_info["medium"])
        
        # Channel type display
        channel_display = {
            "telegram": "Telegram",
            "whatsapp": "WhatsApp",
            "instagram": "Instagram",
            "webchat": "Web Chat"
        }.get(channel_type, channel_type.title())
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Customer Escalation Alert</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1 style="margin: 0; font-size: 24px;">🚨 Customer Escalation Alert</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">{workspace_name}</p>
            </div>
            
            <div style="background: #f8fafc; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #e2e8f0;">
                <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid {priority_data['color']};">
                    <h2 style="margin: 0 0 15px 0; color: {priority_data['color']};">
                        {priority_data['emoji']} {priority_data['label']}
                    </h2>
                    <p style="margin: 0; font-size: 16px;"><strong>Reason:</strong> {escalation_reason}</p>
                </div>
                
                <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="margin: 0 0 15px 0; color: #374151;">Customer Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Contact:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{contact_name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Channel:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{channel_display}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Conversation ID:</strong></td>
                            <td style="padding: 8px 0; font-family: monospace; font-size: 12px;">{conversation_id}</td>
                        </tr>
                    </table>
                </div>
                
                <div style="text-align: center; margin-top: 30px;">
                    <a href="{settings.APP_URL}/conversations/{conversation_id}" 
                       style="background: #4f46e5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                        View Conversation
                    </a>
                </div>
                
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e2e8f0; text-align: center; color: #6b7280; font-size: 14px;">
                    <p>This alert was sent because a customer message was escalated and requires human attention.</p>
                    <p>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Customer Escalation Alert - {workspace_name}
        
        Priority: {priority_data['label']}
        Reason: {escalation_reason}
        
        Customer Details:
        - Contact: {contact_name}
        - Channel: {channel_display}
        - Conversation ID: {conversation_id}
        
        Please log in to your dashboard to view and respond to this escalation.
        
        Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
        """
        
        return await self.send_email(
            to_email=workspace_owner_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
    
    async def send_agent_invitation(
        self,
        agent_email: str,
        agent_name: str,
        workspace_name: str,
        invitation_token: str,
        invited_by_name: str,
        expires_at: datetime
    ) -> Dict[str, Any]:
        """
        Send agent invitation email
        
        Args:
            agent_email: Agent email address
            agent_name: Agent name
            workspace_name: Workspace name
            invitation_token: Invitation token
            invited_by_name: Name of person who sent invitation
            expires_at: Invitation expiration date
        
        Returns:
            Email sending result
        """
        subject = f"You're invited to join {workspace_name} as an agent"
        
        # Create invitation acceptance URL
        accept_url = f"{settings.APP_URL}/accept-invitation?token={invitation_token}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Agent Invitation</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
                <h1 style="margin: 0; font-size: 24px;">🎉 You're Invited!</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">Join {workspace_name} as a Customer Support Agent</p>
            </div>
            
            <div style="background: #f8fafc; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #e2e8f0;">
                <div style="background: white; padding: 25px; border-radius: 8px; margin-bottom: 25px;">
                    <p style="margin: 0 0 20px 0; font-size: 16px;">Hi {agent_name},</p>
                    
                    <p style="margin: 0 0 20px 0;">
                        <strong>{invited_by_name}</strong> has invited you to join <strong>{workspace_name}</strong> 
                        as a customer support agent. You'll be able to help customers, manage conversations, 
                        and provide excellent support.
                    </p>
                    
                    <div style="background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 6px; padding: 15px; margin: 20px 0;">
                        <h3 style="margin: 0 0 10px 0; color: #0369a1;">What you'll be able to do:</h3>
                        <ul style="margin: 0; padding-left: 20px; color: #374151;">
                            <li>Respond to customer messages in real-time</li>
                            <li>Handle escalated conversations</li>
                            <li>Access customer conversation history</li>
                            <li>Collaborate with other team members</li>
                        </ul>
                    </div>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{accept_url}" 
                       style="background: #10b981; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; display: inline-block;">
                        Accept Invitation
                    </a>
                </div>
                
                <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="margin: 0 0 15px 0; color: #374151;">Invitation Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Workspace:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{workspace_name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Invited by:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{invited_by_name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;"><strong>Your email:</strong></td>
                            <td style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">{agent_email}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Expires:</strong></td>
                            <td style="padding: 8px 0; color: #dc2626;">{expires_at.strftime('%B %d, %Y at %H:%M UTC')}</td>
                        </tr>
                    </table>
                </div>
                
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e2e8f0; text-align: center; color: #6b7280; font-size: 14px;">
                    <p>This invitation will expire in 7 days. If you have any questions, please contact {invited_by_name}.</p>
                    <p>If you can't click the button above, copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; font-family: monospace; background: #f3f4f6; padding: 10px; border-radius: 4px;">
                        {accept_url}
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        You're invited to join {workspace_name} as a Customer Support Agent!
        
        Hi {agent_name},
        
        {invited_by_name} has invited you to join {workspace_name} as a customer support agent.
        
        What you'll be able to do:
        - Respond to customer messages in real-time
        - Handle escalated conversations
        - Access customer conversation history
        - Collaborate with other team members
        
        Invitation Details:
        - Workspace: {workspace_name}
        - Invited by: {invited_by_name}
        - Your email: {agent_email}
        - Expires: {expires_at.strftime('%B %d, %Y at %H:%M UTC')}
        
        To accept this invitation, visit:
        {accept_url}
        
        This invitation will expire in 7 days. If you have any questions, please contact {invited_by_name}.
        """
        
        return await self.send_email(
            to_email=agent_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
    
    async def send_test_email(
        self,
        to_email: str,
        test_type: str = "connection"
    ) -> Dict[str, Any]:
        """
        Send test email to verify email service configuration
        
        Args:
            to_email: Test recipient email
            test_type: Type of test email
        
        Returns:
            Email sending result
        """
        subject = "Email Service Test - ChatSaaS"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Email Test</title>
        </head>
        <body style="font-family: Arial, sans-serif; padding: 20px; max-width: 500px; margin: 0 auto;">
            <div style="text-align: center; padding: 20px; background: #f0f9ff; border-radius: 8px;">
                <h2 style="color: #0369a1; margin: 0 0 15px 0;">✅ Email Service Test</h2>
                <p style="margin: 0; color: #374151;">
                    This is a test email from your ChatSaaS email service. 
                    If you received this, your email configuration is working correctly!
                </p>
                <p style="margin: 15px 0 0 0; font-size: 14px; color: #6b7280;">
                    Test Type: {test_type}<br>
                    Sent: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
                </p>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Email Service Test - ChatSaaS
        
        This is a test email from your ChatSaaS email service.
        If you received this, your email configuration is working correctly!
        
        Test Type: {test_type}
        Sent: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
        """
        
        return await self.send_email(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )


# ─── Global Email Service Instance ────────────────────────────────────────────

email_service = EmailService()


# ─── Convenience Functions ────────────────────────────────────────────────────

async def send_escalation_alert_email(
    workspace_owner_email: str,
    workspace_name: str,
    conversation_id: str,
    escalation_reason: str,
    priority: str = "medium",
    contact_name: str = "Unknown",
    channel_type: str = "unknown"
) -> bool:
    """
    Convenience function to send escalation alert email
    
    Args:
        workspace_owner_email: Owner email
        workspace_name: Workspace name
        conversation_id: Conversation ID
        escalation_reason: Escalation reason
        priority: Priority level
        contact_name: Customer name
        channel_type: Channel type
    
    Returns:
        True if email sent successfully
    """
    try:
        await email_service.send_escalation_alert(
            workspace_owner_email=workspace_owner_email,
            workspace_name=workspace_name,
            conversation_id=conversation_id,
            escalation_reason=escalation_reason,
            priority=priority,
            contact_name=contact_name,
            channel_type=channel_type
        )
        return True
    except EmailError as e:
        print(f"Failed to send escalation alert email: {e}")
        return False


async def send_agent_invitation_email(
    agent_email: str,
    agent_name: str,
    workspace_name: str,
    invitation_token: str,
    invited_by_name: str,
    expires_at: datetime
) -> bool:
    """
    Convenience function to send agent invitation email
    
    Args:
        agent_email: Agent email
        agent_name: Agent name
        workspace_name: Workspace name
        invitation_token: Invitation token
        invited_by_name: Inviter name
        expires_at: Expiration date
    
    Returns:
        True if email sent successfully
    """
    try:
        await email_service.send_agent_invitation(
            agent_email=agent_email,
            agent_name=agent_name,
            workspace_name=workspace_name,
            invitation_token=invitation_token,
            invited_by_name=invited_by_name,
            expires_at=expires_at
        )
        return True
    except EmailError as e:
        print(f"Failed to send agent invitation email: {e}")
        return False