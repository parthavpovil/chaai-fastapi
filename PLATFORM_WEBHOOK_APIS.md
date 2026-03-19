# Platform Webhook APIs - Real Implementation Guide

## YES, You Can Literally Do This!

All three platforms (Telegram, WhatsApp, Instagram) officially support setting webhook URLs programmatically. Here's exactly how:

---

## 1. Telegram - setWebhook API

### Official Documentation
https://core.telegram.org/bots/api#setwebhook

### API Endpoint
```
POST https://api.telegram.org/bot{BOT_TOKEN}/setWebhook
```

### Real Example

```bash
# Client A creates Telegram channel with bot token: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

curl -X POST "https://api.telegram.org/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://yourdomain.com/api/webhooks/telegram/123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "secret_token": "your_platform_secret_abc123"
  }'
```

### Response
```json
{
  "ok": true,
  "result": true,
  "description": "Webhook was set"
}
```

### What Happens Next
When someone messages this bot, Telegram will send:
```http
POST https://yourdomain.com/api/webhooks/telegram/123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
X-Telegram-Bot-Api-Secret-Token: your_platform_secret_abc123
Content-Type: application/json

{
  "update_id": 123456789,
  "message": {
    "message_id": 1,
    "from": {
      "id": 987654321,
      "first_name": "John"
    },
    "chat": {
      "id": 987654321,
      "type": "private"
    },
    "text": "Hello!"
  }
}
```

### Your Code Implementation

```python
# backend/app/services/telegram_service.py

import httpx
from app.config import settings

async def setup_telegram_webhook(bot_token: str) -> bool:
    """
    Configure Telegram webhook for a client's bot
    
    Args:
        bot_token: Client's Telegram bot token (e.g., "123456:ABC-DEF...")
    
    Returns:
        True if webhook was set successfully
    """
    webhook_url = f"https://{settings.DOMAIN}/api/webhooks/telegram/{bot_token}"
    
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    
    payload = {
        "url": webhook_url,
        "secret_token": settings.TELEGRAM_SECRET_TOKEN,  # Your platform secret
        "max_connections": 40,
        "allowed_updates": ["message", "callback_query"]
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(telegram_api_url, json=payload)
        result = response.json()
        
        if result.get("ok"):
            print(f"✅ Telegram webhook set for bot: {bot_token[:10]}...")
            return True
        else:
            print(f"❌ Failed to set webhook: {result.get('description')}")
            return False
```

---

## 2. WhatsApp - Webhook Configuration

### Official Documentation
https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/setup

### Setup Method
WhatsApp webhooks are configured through the Meta Developer Console, but you can also use the Graph API.

### Manual Setup (Meta Console)
1. Go to https://developers.facebook.com/apps/
2. Select your app → WhatsApp → Configuration
3. Set Webhook URL: `https://yourdomain.com/api/webhooks/whatsapp/{phone_number_id}`
4. Set Verify Token: Any string you choose (for initial verification)
5. Subscribe to webhook fields: `messages`

### Programmatic Setup (Graph API)

```bash
# Subscribe to webhooks for a specific phone number
curl -X POST "https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/subscribed_apps" \
  -H "Authorization: Bearer {ACCESS_TOKEN}" \
  -d "subscribed_fields=messages"
```

### Webhook Verification Endpoint
WhatsApp will first verify your endpoint:

```http
GET https://yourdomain.com/api/webhooks/whatsapp/{phone_number_id}?hub.mode=subscribe&hub.challenge=123456&hub.verify_token=your_verify_token
```

Your server must respond with the challenge:
```python
@router.get("/whatsapp/{phone_number_id}")
async def whatsapp_webhook_verification(phone_number_id: str, request: Request):
    challenge = request.query_params.get("hub.challenge")
    verify_token = request.query_params.get("hub.verify_token")
    
    # Verify the token matches your expected value
    if verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    
    return Response(status_code=403)
```

### What Happens Next
When someone messages the WhatsApp number, Meta will send:

```http
POST https://yourdomain.com/api/webhooks/whatsapp/123456789
X-Hub-Signature-256: sha256=abc123def456...
Content-Type: application/json

{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "123456789",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "15551234567",
          "phone_number_id": "123456789"
        },
        "messages": [{
          "from": "15559876543",
          "id": "wamid.xxx",
          "timestamp": "1234567890",
          "text": {
            "body": "Hello!"
          },
          "type": "text"
        }]
      }
    }]
  }]
}
```

### Your Code Implementation

```python
# backend/app/services/whatsapp_service.py

async def setup_whatsapp_webhook(phone_number_id: str, access_token: str) -> bool:
    """
    Subscribe WhatsApp phone number to webhooks
    
    Args:
        phone_number_id: WhatsApp phone number ID
        access_token: Client's WhatsApp access token
    
    Returns:
        True if subscription was successful
    """
    graph_api_url = f"https://graph.facebook.com/v18.0/{phone_number_id}/subscribed_apps"
    
    payload = {
        "subscribed_fields": "messages"
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(graph_api_url, json=payload, headers=headers)
        result = response.json()
        
        if result.get("success"):
            print(f"✅ WhatsApp webhook subscribed for: {phone_number_id}")
            return True
        else:
            print(f"❌ Failed to subscribe: {result}")
            return False
```

---

## 3. Instagram - Webhook Configuration

### Official Documentation
https://developers.facebook.com/docs/messenger-platform/webhooks

### Setup Method
Instagram uses the same Meta platform as WhatsApp.

### Manual Setup (Meta Console)
1. Go to https://developers.facebook.com/apps/
2. Select your app → Messenger → Settings
3. Set Webhook URL: `https://yourdomain.com/api/webhooks/instagram/{page_id}`
4. Set Verify Token: Any string you choose
5. Subscribe to webhook fields: `messages`, `messaging_postbacks`

### Programmatic Setup (Graph API)

```bash
# Subscribe Instagram page to webhooks
curl -X POST "https://graph.facebook.com/v18.0/{PAGE_ID}/subscribed_apps" \
  -H "Authorization: Bearer {PAGE_ACCESS_TOKEN}" \
  -d "subscribed_fields=messages,messaging_postbacks"
```

### Webhook Verification (Same as WhatsApp)

```http
GET https://yourdomain.com/api/webhooks/instagram/{page_id}?hub.mode=subscribe&hub.challenge=123456&hub.verify_token=your_verify_token
```

### What Happens Next
When someone messages the Instagram page:

```http
POST https://yourdomain.com/api/webhooks/instagram/987654321
X-Hub-Signature-256: sha256=xyz789abc123...
Content-Type: application/json

{
  "object": "instagram",
  "entry": [{
    "id": "987654321",
    "time": 1234567890,
    "messaging": [{
      "sender": {
        "id": "1122334455"
      },
      "recipient": {
        "id": "987654321"
      },
      "timestamp": 1234567890,
      "message": {
        "mid": "mid.xxx",
        "text": "Hello!"
      }
    }]
  }]
}
```

---

## Complete Implementation in Your System

### When Client Creates a Channel

```python
# backend/app/routers/channels.py

@router.post("/")
async def create_channel(
    channel_data: ChannelCreate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Create a new channel and configure webhook"""
    
    # 1. Validate and encrypt credentials
    if channel_data.type == "telegram":
        bot_token = channel_data.config.get("bot_token")
        encrypted_config = encrypt_channel_config({"bot_token": bot_token})
        
        # 2. Store in database
        channel = Channel(
            workspace_id=current_workspace.id,
            type="telegram",
            name=channel_data.name,
            encrypted_config=encrypted_config,
            is_active=True
        )
        db.add(channel)
        await db.commit()
        
        # 3. Configure webhook with Telegram
        from app.services.telegram_service import setup_telegram_webhook
        webhook_success = await setup_telegram_webhook(bot_token)
        
        if not webhook_success:
            # Rollback if webhook setup fails
            await db.delete(channel)
            await db.commit()
            raise HTTPException(500, "Failed to configure Telegram webhook")
        
        return {"id": channel.id, "status": "active", "webhook": "configured"}
    
    elif channel_data.type == "whatsapp":
        phone_number_id = channel_data.config.get("phone_number_id")
        access_token = channel_data.config.get("access_token")
        
        encrypted_config = encrypt_channel_config({
            "phone_number_id": phone_number_id,
            "access_token": access_token
        })
        
        channel = Channel(
            workspace_id=current_workspace.id,
            type="whatsapp",
            name=channel_data.name,
            encrypted_config=encrypted_config,
            is_active=True
        )
        db.add(channel)
        await db.commit()
        
        # Configure webhook with WhatsApp
        from app.services.whatsapp_service import setup_whatsapp_webhook
        webhook_success = await setup_whatsapp_webhook(phone_number_id, access_token)
        
        if not webhook_success:
            await db.delete(channel)
            await db.commit()
            raise HTTPException(500, "Failed to configure WhatsApp webhook")
        
        return {"id": channel.id, "status": "active", "webhook": "configured"}
```

---

## Real-World Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CLIENT CREATES CHANNEL                           │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  v
┌─────────────────────────────────────────────────────────────────────┐
│ Client provides credentials via your API:                           │
│ POST /api/channels                                                  │
│ {                                                                   │
│   "type": "telegram",                                               │
│   "name": "Customer Support Bot",                                   │
│   "config": {                                                       │
│     "bot_token": "123456:ABC-DEF..."                                │
│   }                                                                 │
│ }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  v
┌─────────────────────────────────────────────────────────────────────┐
│ Your System:                                                        │
│ 1. Encrypts bot_token                                               │
│ 2. Stores in database (channels table)                              │
│ 3. Calls Telegram API:                                              │
│    POST https://api.telegram.org/bot123456:ABC-DEF.../setWebhook   │
│    {                                                                │
│      "url": "https://yourdomain.com/api/webhooks/telegram/123...", │
│      "secret_token": "your_platform_secret"                         │
│    }                                                                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  v
┌─────────────────────────────────────────────────────────────────────┐
│ Telegram Response:                                                  │
│ {                                                                   │
│   "ok": true,                                                       │
│   "result": true,                                                   │
│   "description": "Webhook was set"                                  │
│ }                                                                   │
│                                                                     │
│ ✅ Webhook is now configured!                                       │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  v
┌─────────────────────────────────────────────────────────────────────┐
│                    CUSTOMER SENDS MESSAGE                           │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  v
┌─────────────────────────────────────────────────────────────────────┐
│ Telegram sends webhook to YOUR server:                             │
│ POST https://yourdomain.com/api/webhooks/telegram/123456:ABC-DEF...│
│ X-Telegram-Bot-Api-Secret-Token: your_platform_secret              │
│ {                                                                   │
│   "message": {                                                      │
│     "text": "Hello, I need help!"                                   │
│   }                                                                 │
│ }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  v
┌─────────────────────────────────────────────────────────────────────┐
│ Your System:                                                        │
│ 1. Verifies secret_token matches TELEGRAM_SECRET_TOKEN ✅          │
│ 2. Extracts bot_token from URL: "123456:ABC-DEF..."                │
│ 3. Looks up in database → Finds Client A's workspace               │
│ 4. Processes message for Client A                                   │
│ 5. Sends response using Client A's bot_token                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Testing It Yourself

### Test Telegram Webhook Setup

```bash
# Replace with your actual bot token
BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
YOUR_DOMAIN="yourdomain.com"
YOUR_SECRET="abc123xyz"

# Set webhook
curl -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"https://${YOUR_DOMAIN}/api/webhooks/telegram/${BOT_TOKEN}\",
    \"secret_token\": \"${YOUR_SECRET}\"
  }"

# Check webhook info
curl "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
```

### Expected Response

```json
{
  "ok": true,
  "result": {
    "url": "https://yourdomain.com/api/webhooks/telegram/123456:ABC-DEF...",
    "has_custom_certificate": false,
    "pending_update_count": 0,
    "max_connections": 40,
    "ip_address": "1.2.3.4"
  }
}
```

---

## Summary

### ✅ YES, You Can Do This!

| Platform | Method | URL Pattern | Secret Method |
|----------|--------|-------------|---------------|
| **Telegram** | API Call | `/telegram/{bot_token}` | `secret_token` parameter |
| **WhatsApp** | Meta Console + API | `/whatsapp/{phone_number_id}` | HMAC signature |
| **Instagram** | Meta Console + API | `/instagram/{page_id}` | HMAC signature |

### Key Points:

1. **Each bot/channel gets its own webhook URL** with its identifier in the path
2. **All webhooks use the same platform secret** for verification
3. **This is officially supported** by all three platforms
4. **Your system automatically configures this** when clients create channels

### The Magic:

- Telegram allows you to set a different webhook URL for each bot token
- WhatsApp allows you to set webhook URL per phone number
- Instagram allows you to set webhook URL per page

This is exactly how multi-tenant chatbot platforms work! 🚀
