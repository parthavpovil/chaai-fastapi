"""
Webhook Processing Router
Handles incoming webhooks from all channel types with background processing
"""
import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.services.webhook_handlers import WebhookHandlers, WebhookProcessingError
from app.services.message_processor import process_incoming_message, MessageProcessingError
from app.services.escalation_router import check_and_escalate_message
from app.services.rag_engine import generate_rag_response
from app.services.usage_tracker import track_message_usage
from app.services.websocket_events import notify_new_message


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ─── Webhook Endpoints ────────────────────────────────────────────────────────

@router.post("/telegram/{bot_token}")
async def telegram_webhook(
    bot_token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Telegram webhook endpoint
    
    Args:
        bot_token: Telegram bot token for channel identification
        request: FastAPI request object
        background_tasks: Background task manager
        db: Database session
    
    Returns:
        HTTP 200 response immediately
    """
    try:
        # Get raw payload and headers
        payload = await request.body()
        headers = dict(request.headers)
        
        # Return HTTP 200 immediately
        response = Response(status_code=200, content="OK")
        
        # Process webhook in background
        background_tasks.add_task(
            process_webhook_background,
            "telegram",
            payload,
            headers,
            bot_token,
            db
        )
        
        return response
        
    except Exception as e:
        # Log error but still return 200 to avoid webhook retries
        print(f"Telegram webhook error: {e}")
        return Response(status_code=200, content="OK")


@router.post("/whatsapp/{phone_number_id}")
async def whatsapp_webhook(
    phone_number_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    WhatsApp webhook endpoint
    
    Args:
        phone_number_id: WhatsApp phone number ID for channel identification
        request: FastAPI request object
        background_tasks: Background task manager
        db: Database session
    
    Returns:
        HTTP 200 response immediately
    """
    try:
        # Get raw payload and headers
        payload = await request.body()
        headers = dict(request.headers)
        
        # Return HTTP 200 immediately
        response = Response(status_code=200, content="OK")
        
        # Process webhook in background
        background_tasks.add_task(
            process_webhook_background,
            "whatsapp",
            payload,
            headers,
            phone_number_id,
            db
        )
        
        return response
        
    except Exception as e:
        # Log error but still return 200 to avoid webhook retries
        print(f"WhatsApp webhook error: {e}")
        return Response(status_code=200, content="OK")


@router.get("/whatsapp/{phone_number_id}")
async def whatsapp_webhook_verification(
    phone_number_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    WhatsApp webhook verification endpoint
    Handles Meta verification challenges
    
    Args:
        phone_number_id: WhatsApp phone number ID
        request: FastAPI request object
        db: Database session
    
    Returns:
        Challenge response for verification
    """
    try:
        # Get query parameters
        query_params = dict(request.query_params)
        
        # Handle Meta verification challenge
        if "hub.challenge" in query_params:
            challenge = query_params.get("hub.challenge")
            verify_token = query_params.get("hub.verify_token")
            
            # In production, verify the verify_token matches your expected value
            # For now, we'll accept any verification challenge
            print(f"WhatsApp verification challenge: {challenge}, token: {verify_token}")
            
            return Response(content=challenge, media_type="text/plain")
        
        return Response(status_code=400, content="Bad Request")
        
    except Exception as e:
        print(f"WhatsApp verification error: {e}")
        return Response(status_code=400, content="Bad Request")


@router.post("/instagram/{page_id}")
async def instagram_webhook(
    page_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Instagram webhook endpoint
    
    Args:
        page_id: Instagram page ID for channel identification
        request: FastAPI request object
        background_tasks: Background task manager
        db: Database session
    
    Returns:
        HTTP 200 response immediately
    """
    try:
        # Get raw payload and headers
        payload = await request.body()
        headers = dict(request.headers)
        
        # Return HTTP 200 immediately
        response = Response(status_code=200, content="OK")
        
        # Process webhook in background
        background_tasks.add_task(
            process_webhook_background,
            "instagram",
            payload,
            headers,
            page_id,
            db
        )
        
        return response
        
    except Exception as e:
        # Log error but still return 200 to avoid webhook retries
        print(f"Instagram webhook error: {e}")
        return Response(status_code=200, content="OK")


@router.get("/instagram/{page_id}")
async def instagram_webhook_verification(
    page_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Instagram webhook verification endpoint
    Handles Meta verification challenges
    
    Args:
        page_id: Instagram page ID
        request: FastAPI request object
        db: Database session
    
    Returns:
        Challenge response for verification
    """
    try:
        # Get query parameters
        query_params = dict(request.query_params)
        
        # Handle Meta verification challenge
        if "hub.challenge" in query_params:
            challenge = query_params.get("hub.challenge")
            verify_token = query_params.get("hub.verify_token")
            
            # In production, verify the verify_token matches your expected value
            # For now, we'll accept any verification challenge
            print(f"Instagram verification challenge: {challenge}, token: {verify_token}")
            
            return Response(content=challenge, media_type="text/plain")
        
        return Response(status_code=400, content="Bad Request")
        
    except Exception as e:
        print(f"Instagram verification error: {e}")
        return Response(status_code=400, content="Bad Request")


# ─── Background Processing Pipeline ───────────────────────────────────────────

async def process_webhook_background(
    channel_type: str,
    payload: bytes,
    headers: Dict[str, str],
    identifier: str,
    db: AsyncSession
):
    """
    Background task for processing webhooks
    
    Args:
        channel_type: Channel type
        payload: Raw webhook payload
        headers: Request headers
        identifier: Channel identifier
        db: Database session
    """
    try:
        # Step 1: Process webhook and extract message data
        handlers = WebhookHandlers(db)
        
        if channel_type == "telegram":
            webhook_result = await handlers.handle_telegram_webhook(payload, headers, identifier)
        elif channel_type == "whatsapp":
            webhook_result = await handlers.handle_whatsapp_webhook(payload, headers, identifier)
        elif channel_type == "instagram":
            webhook_result = await handlers.handle_instagram_webhook(payload, headers, identifier)
        else:
            print(f"Unsupported channel type: {channel_type}")
            return
        
        # Handle verification challenges
        if webhook_result.get("status") == "verification":
            print(f"Handled {channel_type} verification challenge")
            return
        
        # Skip if no processable message
        if webhook_result.get("status") != "success":
            print(f"Webhook ignored: {webhook_result.get('reason', 'Unknown')}")
            return
        
        # Step 2: Process incoming message through message processor
        message_data = webhook_result["message_data"]
        workspace_id = webhook_result["workspace_id"]
        channel_id = webhook_result["channel_id"]
        
        processing_result = await process_incoming_message(
            db=db,
            workspace_id=workspace_id,
            channel_id=channel_id,
            external_contact_id=message_data["external_contact_id"],
            content=message_data["content"],
            external_message_id=message_data.get("external_message_id"),
            contact_name=message_data.get("contact_name"),
            contact_data=message_data.get("contact_data"),
            message_metadata=message_data.get("message_metadata")
        )
        
        conversation_id = processing_result["conversation"]["id"]
        message_id = processing_result["message"]["id"]
        
        # Send WebSocket notification for customer message
        await notify_new_message(
            db=db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id
        )
        
        # Step 3: Check for escalation
        escalation_result = await check_and_escalate_message(
            db=db,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            message_content=message_data["content"]
        )
        
        if escalation_result:
            print(f"Message escalated: {escalation_result['escalation_reason']}")
            # Escalation handling is complete, no AI response needed
            return
        
        # Step 4: Generate RAG response
        try:
            rag_result = await generate_rag_response(
                db=db,
                workspace_id=workspace_id,
                query=message_data["content"],
                conversation_id=conversation_id,
                max_tokens=300
            )
            
            response_content = rag_result["response"]
            input_tokens = rag_result["input_tokens"]
            output_tokens = rag_result["output_tokens"]
            
        except Exception as e:
            print(f"RAG response generation failed: {e}")
            # Use fallback response
            response_content = "I'm sorry, I'm having trouble processing your request right now. Please try again later."
            input_tokens = 0
            output_tokens = 0
        
        # Step 5: Create assistant response message
        from app.services.message_processor import MessageProcessor
        processor = MessageProcessor(db)
        
        response_message = await processor.create_message(
            conversation_id=conversation_id,
            content=response_content,
            role="assistant",
            channel_type=channel_type,
            metadata={
                "rag_used": True,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "platform_response": True
            }
        )
        
        # Step 6: Track usage
        await track_message_usage(
            db=db,
            workspace_id=workspace_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
        
        # Step 7: Send WebSocket notification
        await notify_new_message(
            db=db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=response_message.id
        )
        
        # Step 8: Send response back to platform (if needed)
        try:
            await send_platform_response(
                channel_type=channel_type,
                channel_id=channel_id,
                external_contact_id=message_data["external_contact_id"],
                response_content=response_content,
                db=db
            )
        except Exception as e:
            print(f"Failed to send platform response: {e}")
            # Don't fail the entire pipeline if platform response fails
        
        print(f"Webhook processing completed for {channel_type}")
        
    except MessageProcessingError as e:
        print(f"Message processing error: {e}")
        # For maintenance mode or duplicate messages, this is expected
        if "maintenance" in str(e).lower() or "duplicate" in str(e).lower():
            return
        # For other processing errors, we might want to alert
        await handle_processing_error(channel_type, str(e), db)
    except WebhookProcessingError as e:
        print(f"Webhook processing error: {e}")
        await handle_processing_error(channel_type, str(e), db)
    except Exception as e:
        print(f"Unexpected error in webhook processing: {e}")
        await handle_processing_error(channel_type, f"Unexpected error: {str(e)}", db)


# ─── Platform Response Integration ────────────────────────────────────────────

async def send_platform_response(
    channel_type: str,
    channel_id: str,
    external_contact_id: str,
    response_content: str,
    db: AsyncSession
) -> bool:
    """
    Send response back to the platform (Telegram, WhatsApp, Instagram)
    
    Args:
        channel_type: Channel type
        channel_id: Channel ID
        external_contact_id: External contact ID
        response_content: Response content to send
        db: Database session
    
    Returns:
        True if response sent successfully
    
    Note:
        This is a placeholder for platform API integration.
        In production, this would make actual API calls to send messages.
    """
    try:
        # Get channel credentials for API calls
        from sqlalchemy import select
        from app.models.channel import Channel
        from app.services.encryption import decrypt_credential
        
        result = await db.execute(
            select(Channel)
            .where(Channel.id == channel_id)
            .where(Channel.is_active == True)
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            print(f"Channel {channel_id} not found or inactive")
            return False
        
        # Platform-specific response sending
        if channel_type == "telegram":
            return await send_telegram_response(channel, external_contact_id, response_content)
        elif channel_type == "whatsapp":
            return await send_whatsapp_response(channel, external_contact_id, response_content)
        elif channel_type == "instagram":
            return await send_instagram_response(channel, external_contact_id, response_content)
        else:
            print(f"Platform response not implemented for {channel_type}")
            return False
            
    except Exception as e:
        print(f"Platform response error: {e}")
        return False


async def send_telegram_response(
    channel: "Channel",
    chat_id: str,
    text: str
) -> bool:
    """
    Send response via Telegram Bot API
    
    Args:
        channel: Channel instance with credentials
        chat_id: Telegram chat ID
        text: Message text to send
    
    Returns:
        True if sent successfully
    """
    try:
        # This would make actual API call to Telegram
        # For now, just log the response
        print(f"Telegram response to {chat_id}: {text[:100]}...")
        return True
        
        # TODO: Implement actual Telegram API call
        # from app.services.encryption import decrypt_credential
        # import httpx
        # 
        # bot_token = decrypt_credential(channel.encrypted_config["bot_token"])
        # url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        # 
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(url, json={
        #         "chat_id": chat_id,
        #         "text": text
        #     })
        #     return response.status_code == 200
        
    except Exception as e:
        print(f"Telegram response error: {e}")
        return False


async def send_whatsapp_response(
    channel: "Channel",
    phone_number: str,
    text: str
) -> bool:
    """
    Send response via WhatsApp Business API
    
    Args:
        channel: Channel instance with credentials
        phone_number: WhatsApp phone number
        text: Message text to send
    
    Returns:
        True if sent successfully
    """
    try:
        # This would make actual API call to WhatsApp
        # For now, just log the response
        print(f"WhatsApp response to {phone_number}: {text[:100]}...")
        return True
        
        # TODO: Implement actual WhatsApp API call
        
    except Exception as e:
        print(f"WhatsApp response error: {e}")
        return False


async def send_instagram_response(
    channel: "Channel",
    sender_id: str,
    text: str
) -> bool:
    """
    Send response via Instagram Messaging API
    
    Args:
        channel: Channel instance with credentials
        sender_id: Instagram sender ID
        text: Message text to send
    
    Returns:
        True if sent successfully
    """
    try:
        # This would make actual API call to Instagram
        # For now, just log the response
        print(f"Instagram response to {sender_id}: {text[:100]}...")
        return True
        
        # TODO: Implement actual Instagram API call
        
    except Exception as e:
        print(f"Instagram response error: {e}")
        return False


async def handle_processing_error(
    channel_type: str,
    error_message: str,
    db: AsyncSession
) -> None:
    """
    Handle processing errors with appropriate logging and alerting
    
    Args:
        channel_type: Channel type where error occurred
        error_message: Error message
        db: Database session
    """
    try:
        # Log error with context
        error_context = {
            "channel_type": channel_type,
            "error": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        print(f"Processing error logged: {error_context}")
        
        # TODO: In production, this could:
        # 1. Send error alerts to administrators
        # 2. Store errors in a dedicated error tracking table
        # 3. Integrate with error monitoring services (Sentry, etc.)
        # 4. Trigger automated recovery procedures
        
    except Exception as e:
        print(f"Error handling failed: {e}")


# ─── Webhook Health Check ─────────────────────────────────────────────────────

@router.get("/health")
async def webhook_health():
    """
    Webhook service health check
    
    Returns:
        Health status
    """
    return {
        "status": "healthy",
        "service": "webhook_processor",
        "supported_channels": ["telegram", "whatsapp", "instagram"],
        "timestamp": "2024-01-01T00:00:00Z"  # This would be dynamic in real implementation
    }


# ─── Webhook Testing Endpoints ────────────────────────────────────────────────

@router.post("/test/{channel_type}")
async def test_webhook(
    channel_type: str,
    test_payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Test webhook processing without actual platform integration
    
    Args:
        channel_type: Channel type to test
        test_payload: Test payload data
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Processing result
    
    Note:
        This endpoint is for testing purposes and requires authentication
    """
    try:
        # Convert test payload to bytes
        import json
        payload = json.dumps(test_payload).encode('utf-8')
        headers = {"content-type": "application/json"}
        identifier = test_payload.get("identifier", "test")
        
        # Process webhook
        handlers = WebhookHandlers(db)
        
        if channel_type == "telegram":
            result = await handlers.handle_telegram_webhook(payload, headers, identifier)
        elif channel_type == "whatsapp":
            result = await handlers.handle_whatsapp_webhook(payload, headers, identifier)
        elif channel_type == "instagram":
            result = await handlers.handle_instagram_webhook(payload, headers, identifier)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported channel type: {channel_type}"
            )
        
        return {
            "test_result": "success",
            "channel_type": channel_type,
            "processing_result": result
        }
        
    except WebhookProcessingError as e:
        return {
            "test_result": "error",
            "channel_type": channel_type,
            "error": str(e)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Test failed: {str(e)}"
        )