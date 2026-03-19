# Webhook Secrets - Complete Guide

## What Are Webhook Secrets?

Webhook secrets are used to **verify that incoming webhooks are authentic** and not from attackers trying to inject fake messages into your system.

## The Problem They Solve

Without webhook secrets:
```
❌ Attacker → Fake webhook → Your server → Processes fake message
```

With webhook secrets:
```
✅ Telegram → Webhook + Signature → Your server → Verifies → Processes
❌ Attacker → Fake webhook → Your server → Invalid signature → Rejects
```

---

## How Each Platform Works

### 1. Telegram Webhook Security

#### Step 1: You Generate a Secret Token
```bash
# Generate a random secret token
openssl rand -hex 16
# Output: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

#### Step 2: Set Telegram Webhook with Your Secret
When you (or your client) sets up the Telegram bot webhook, you include this secret:

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://yourdomain.com/api/webhooks/telegram",
    "secret_token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
  }'
```

#### Step 3: Telegram Sends Webhooks with Secret
When Telegram sends a webhook to your server, it includes the secret in the header:

```http
POST /api/webhooks/telegram
X-Telegram-Bot-Api-Secret-Token: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
Content-Type: application/json

{
  "message": {
    "text": "Hello from customer"
  }
}
```

#### Step 4: Your Server Verifies the Secret
Your code checks if the secret matches:

```python
# In your webhook handler
incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
expected_secret = settings.TELEGRAM_SECRET_TOKEN

if incoming_secret != expected_secret:
    raise HTTPException(403, "Invalid secret token")

# Process webhook...
```

---

### 2. WhatsApp Webhook Security

#### Step 1: Create WhatsApp App on Meta
1. Go to https://developers.facebook.com/apps/
2. Create new app
3. Add WhatsApp product
4. Meta generates an **App Secret** for you

#### Step 2: Meta Provides the App Secret
```
App Secret: abc123xyz789def456ghi012jkl345
```

#### Step 3: WhatsApp Sends Webhooks with Signature
When WhatsApp sends a webhook, it includes a signature:

```http
POST /api/webhooks/whatsapp
X-Hub-Signature-256: sha256=abc123...
Content-Type: application/json

{
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{"text": "Hello"}]
      }
    }]
  }]
}
```

#### Step 4: Your Server Verifies the Signature
Your code calculates the expected signature and compares:

```python
import hmac
import hashlib

# Get signature from header
signature_header = request.headers.get("X-Hub-Signature-256")
expected_signature = signature_header.split("sha256=")[1]

# Calculate signature using app secret
body = await request.body()
calculated_signature = hmac.new(
    settings.WHATSAPP_APP_SECRET.encode(),
    body,
    hashlib.sha256
).hexdigest()

if calculated_signature != expected_signature:
    raise HTTPException(403, "Invalid signature")

# Process webhook...
```

---

### 3. Instagram Webhook Security

Works exactly like WhatsApp (same Meta platform):

#### Step 1: Create Instagram App on Meta
1. Go to https://developers.facebook.com/apps/
2. Create new app or use existing
3. Add Instagram product
4. Meta generates an **App Secret**

#### Step 2: Instagram Sends Webhooks with Signature
```http
POST /api/webhooks/instagram
X-Hub-Signature-256: sha256=xyz789...
Content-Type: application/json

{
  "entry": [{
    "messaging": [{
      "message": {"text": "Hello"}
    }]
  }]
}
```

#### Step 3: Your Server Verifies (Same as WhatsApp)
```python
# Same verification code as WhatsApp
```

---

## Complete Setup Guide

### For Telegram

#### 1. Generate Secret Token
```bash
# On your local machine
openssl rand -hex 16
# Copy output: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

#### 2. Add to GitHub Secrets
```
Name: TELEGRAM_SECRET_TOKEN
Value: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

#### 3. Configure Telegram Webhook
This happens when a client creates a Telegram channel in your app:

```python
# Your code does this automatically when client adds Telegram channel
import requests

bot_token = "client_provided_bot_token"
webhook_url = "https://yourdomain.com/api/webhooks/telegram"
secret_token = settings.TELEGRAM_SECRET_TOKEN

requests.post(
    f"https://api.telegram.org/bot{bot_token}/setWebhook",
    json={
        "url": webhook_url,
        "secret_token": secret_token
    }
)
```

#### 4. Your Webhook Handler Verifies
```python
# In app/routers/webhooks.py
@router.post("/telegram")
async def telegram_webhook(request: Request):
    # Verify secret token
    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if incoming_secret != settings.TELEGRAM_SECRET_TOKEN:
        raise HTTPException(403, "Invalid secret")
    
    # Process webhook
    data = await request.json()
    # ... handle message
```

---

### For WhatsApp

#### 1. Create Meta App
1. Go to https://developers.facebook.com/apps/
2. Click "Create App"
3. Select "Business" type
4. Fill in app details
5. Add "WhatsApp" product

#### 2. Get App Secret
1. In app dashboard, go to Settings → Basic
2. Copy "App Secret"
3. Example: `abc123xyz789def456ghi012jkl345`

#### 3. Add to GitHub Secrets
```
Name: WHATSAPP_APP_SECRET
Value: abc123xyz789def456ghi012jkl345
```

#### 4. Configure Webhook in Meta Console
1. In WhatsApp settings, go to Configuration
2. Set Webhook URL: `https://yourdomain.com/api/webhooks/whatsapp`
3. Set Verify Token: (any string you choose)
4. Subscribe to message events

#### 5. Your Webhook Handler Verifies
```python
# In app/routers/webhooks.py
import hmac
import hashlib

@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    # Get signature from header
    signature = request.headers.get("X-Hub-Signature-256", "").replace("sha256=", "")
    
    # Calculate expected signature
    body = await request.body()
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    # Verify
    if signature != expected:
        raise HTTPException(403, "Invalid signature")
    
    # Process webhook
    data = await request.json()
    # ... handle message
```

---

### For Instagram

Same process as WhatsApp (uses same Meta app):

#### 1. Use Same Meta App or Create New One
#### 2. Add Instagram Product
#### 3. Get App Secret (same as WhatsApp if using same app)
#### 4. Add to GitHub Secrets
```
Name: INSTAGRAM_APP_SECRET
Value: abc123xyz789def456ghi012jkl345
```

#### 5. Configure Webhook in Meta Console
#### 6. Your Webhook Handler Verifies (same code as WhatsApp)

---

## Important: One Secret Per Platform, Not Per Client

### ❌ WRONG Understanding:
```
Client 1 Telegram → Secret 1
Client 2 Telegram → Secret 2
Client 3 Telegram → Secret 3
```

### ✅ CORRECT Understanding:
```
ALL Telegram webhooks → ONE platform secret
ALL WhatsApp webhooks → ONE platform secret
ALL Instagram webhooks → ONE platform secret
```

### Why?
Because the secret is used to verify the webhook came from the platform (Telegram/WhatsApp/Instagram), not to identify which client it's for.

**Client identification** happens through the bot token or phone number in the webhook payload.

---

## Real-World Example

### Scenario: 3 Clients Using Telegram

#### Setup:
```
Platform Secret (in GitHub): TELEGRAM_SECRET_TOKEN=abc123

Client A: Bot token = 111:AAA
Client B: Bot token = 222:BBB  
Client C: Bot token = 333:CCC
```

#### When Client A's customer sends message:
```
1. Customer → Telegram Bot 111:AAA
2. Telegram → Webhook to your server
   Headers: X-Telegram-Bot-Api-Secret-Token: abc123
   Body: {"message": {"from": {"id": 12345}, "text": "Hello"}}
3. Your server:
   - Verifies secret: abc123 ✅
   - Looks up bot token 111:AAA in database
   - Finds Client A's workspace
   - Processes message for Client A
```

#### When Client B's customer sends message:
```
1. Customer → Telegram Bot 222:BBB
2. Telegram → Webhook to your server
   Headers: X-Telegram-Bot-Api-Secret-Token: abc123 (SAME SECRET!)
   Body: {"message": {"from": {"id": 67890}, "text": "Hi"}}
3. Your server:
   - Verifies secret: abc123 ✅
   - Looks up bot token 222:BBB in database
   - Finds Client B's workspace
   - Processes message for Client B
```

**Same secret, different clients!**

---

## When to Add These Secrets

### Option 1: Add All Now (Recommended)
If you plan to support all channels eventually:

```bash
# Generate Telegram secret
TELEGRAM_SECRET_TOKEN=$(openssl rand -hex 16)

# Get WhatsApp/Instagram secrets from Meta
# (same secret can be used for both if using same app)
WHATSAPP_APP_SECRET=from_meta_console
INSTAGRAM_APP_SECRET=from_meta_console
```

### Option 2: Add Only What You Need
If you're only supporting WebChat initially:
- Don't add any webhook secrets yet
- Add them later when you enable those channels

---

## How Your Code Uses These

Let me show you where these secrets are used in your codebase:

<function_calls>
<invoke name="grepSearch">
<parameter name="explanation">Finding where webhook secrets are used in the code