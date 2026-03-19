# Webhook Security Architecture - Complete Explanation

## The Confusion: Two Types of Secrets

There are **TWO DIFFERENT TYPES** of secrets in your system:

### Type 1: Platform Verification Secrets (GitHub Secrets)
**Purpose**: Verify webhooks come from the actual platform (Telegram/WhatsApp/Instagram), not attackers

### Type 2: Client Credentials (Database - Encrypted)
**Purpose**: Identify which client the webhook belongs to and send responses back

---

## Visual Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         YOUR CHATSAAS PLATFORM                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  GitHub Secrets (Platform-Level - ONE per platform)                    │
│  ┌───────────────────────────────────────────────────────────┐        │
│  │ TELEGRAM_SECRET_TOKEN = "abc123xyz"                       │        │
│  │ WHATSAPP_APP_SECRET = "meta_secret_456"                   │        │
│  │ INSTAGRAM_APP_SECRET = "meta_secret_789"                  │        │
│  └───────────────────────────────────────────────────────────┘        │
│                                                                         │
│  Database (Client-Level - ONE per client per channel)                  │
│  ┌───────────────────────────────────────────────────────────┐        │
│  │ Client A - Telegram Channel                               │        │
│  │   encrypted_config = {                                    │        │
│  │     "bot_token": "111:AAA_encrypted"                      │        │
│  │   }                                                        │        │
│  │                                                            │        │
│  │ Client B - Telegram Channel                               │        │
│  │   encrypted_config = {                                    │        │
│  │     "bot_token": "222:BBB_encrypted"                      │        │
│  │   }                                                        │        │
│  │                                                            │        │
│  │ Client C - WhatsApp Channel                               │        │
│  │   encrypted_config = {                                    │        │
│  │     "phone_number_id": "333_encrypted",                   │        │
│  │     "access_token": "client_c_token_encrypted"            │        │
│  │   }                                                        │        │
│  └───────────────────────────────────────────────────────────┘        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## How It Works: Step-by-Step

### Scenario: Client A's customer sends a Telegram message

```
Step 1: Customer sends message
┌──────────┐
│ Customer │ "Hello, I need help"
└────┬─────┘
     │
     v
┌────────────┐
│  Telegram  │ (Telegram's servers)
│  Platform  │
└────┬───────┘
     │
     │ Webhook with:
     │ - Header: X-Telegram-Bot-Api-Secret-Token: abc123xyz
     │ - Body: {"message": {"from": {"id": 12345}, "text": "Hello"}}
     │ - URL: /api/webhooks/telegram/111:AAA
     │
     v
┌─────────────────────────────────────────────────────────────┐
│              YOUR SERVER - Webhook Handler                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Step 2: VERIFY PLATFORM (using GitHub Secret)              │
│ ┌─────────────────────────────────────────────────┐       │
│ │ incoming_secret = "abc123xyz"                   │       │
│ │ expected_secret = TELEGRAM_SECRET_TOKEN         │       │
│ │                                                  │       │
│ │ if incoming_secret != expected_secret:          │       │
│ │     return 403 Forbidden  ❌ REJECT             │       │
│ │                                                  │       │
│ │ ✅ SECRET MATCHES - Webhook is from Telegram    │       │
│ └─────────────────────────────────────────────────┘       │
│                                                             │
│ Step 3: IDENTIFY CLIENT (using bot_token from URL)         │
│ ┌─────────────────────────────────────────────────┐       │
│ │ bot_token = "111:AAA" (from URL path)           │       │
│ │                                                  │       │
│ │ Query database:                                 │       │
│ │   SELECT * FROM channels                        │       │
│ │   WHERE encrypted_config->>'bot_token' = ?      │       │
│ │                                                  │       │
│ │ Found: Client A's channel                       │       │
│ │   workspace_id = "client-a-workspace-id"        │       │
│ │   channel_id = "client-a-telegram-channel-id"   │       │
│ └─────────────────────────────────────────────────┘       │
│                                                             │
│ Step 4: PROCESS MESSAGE for Client A                       │
│ ┌─────────────────────────────────────────────────┐       │
│ │ - Create conversation for Client A              │       │
│ │ - Store message in Client A's workspace         │       │
│ │ - Generate AI response using Client A's docs    │       │
│ │ - Track usage for Client A                      │       │
│ └─────────────────────────────────────────────────┘       │
│                                                             │
│ Step 5: SEND RESPONSE (using Client A's bot token)         │
│ ┌─────────────────────────────────────────────────┐       │
│ │ bot_token = decrypt("111:AAA_encrypted")        │       │
│ │                                                  │       │
│ │ POST to Telegram API:                           │       │
│ │   https://api.telegram.org/bot111:AAA/sendMessage│      │
│ │   {                                              │       │
│ │     "chat_id": 12345,                           │       │
│ │     "text": "AI response..."                    │       │
│ │   }                                              │       │
│ └─────────────────────────────────────────────────┘       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## The Two-Layer Security Model

### Layer 1: Platform Authentication (GitHub Secrets)
**Question**: "Is this webhook really from Telegram/WhatsApp/Instagram?"

```python
# ONE secret for ALL clients using Telegram
TELEGRAM_SECRET_TOKEN = "abc123xyz"  # In GitHub Secrets

# Verification code (same for all clients)
incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
if incoming_secret != settings.TELEGRAM_SECRET_TOKEN:
    raise HTTPException(403, "Not from Telegram!")
```

**Why ONE secret?**
- You control your server
- You set up ONE webhook URL for all Telegram bots: `https://yourdomain.com/api/webhooks/telegram/{bot_token}`
- Telegram uses YOUR secret to prove it's really Telegram sending the webhook

### Layer 2: Client Identification (Database)
**Question**: "Which client does this webhook belong to?"

```python
# MANY credentials, ONE per client (stored encrypted in database)
# Client A
bot_token_a = "111:AAA"  # Stored encrypted in channels table

# Client B  
bot_token_b = "222:BBB"  # Stored encrypted in channels table

# Client C
bot_token_c = "333:CCC"  # Stored encrypted in channels table

# Identification code
bot_token = path_params["bot_token"]  # From URL: /telegram/111:AAA
channel = db.query(Channel).filter(
    Channel.encrypted_config["bot_token"] == encrypt(bot_token)
).first()

workspace_id = channel.workspace_id  # Now we know it's Client A!
```

---

## Real-World Example: 3 Clients

### Setup Phase (When clients create channels)

```
Client A creates Telegram channel:
├─ Provides: bot_token = "111:AAA"
├─ Your system:
│  ├─ Encrypts: "111:AAA" → "encrypted_111_AAA"
│  ├─ Stores in database: channels table
│  └─ Calls Telegram API:
│     POST https://api.telegram.org/bot111:AAA/setWebhook
│     {
│       "url": "https://yourdomain.com/api/webhooks/telegram/111:AAA",
│       "secret_token": "abc123xyz"  ← YOUR platform secret
│     }

Client B creates Telegram channel:
├─ Provides: bot_token = "222:BBB"
├─ Your system:
│  ├─ Encrypts: "222:BBB" → "encrypted_222_BBB"
│  ├─ Stores in database: channels table
│  └─ Calls Telegram API:
│     POST https://api.telegram.org/bot222:BBB/setWebhook
│     {
│       "url": "https://yourdomain.com/api/webhooks/telegram/222:BBB",
│       "secret_token": "abc123xyz"  ← SAME platform secret!
│     }

Client C creates WhatsApp channel:
├─ Provides: phone_number_id = "333", access_token = "client_c_token"
├─ Your system:
│  ├─ Encrypts both credentials
│  ├─ Stores in database: channels table
│  └─ Configures in Meta Console:
│     Webhook URL: https://yourdomain.com/api/webhooks/whatsapp/333
│     (Meta will use WHATSAPP_APP_SECRET to sign webhooks)
```

### Runtime Phase (When messages arrive)

```
Message to Client A:
┌─────────────────────────────────────────────────────────────┐
│ Telegram → Your Server                                      │
│ POST /api/webhooks/telegram/111:AAA                         │
│ Header: X-Telegram-Bot-Api-Secret-Token: abc123xyz         │
│ Body: {"message": {"text": "Hello"}}                        │
│                                                              │
│ Your Server:                                                 │
│ 1. Verify: abc123xyz == TELEGRAM_SECRET_TOKEN ✅            │
│ 2. Lookup: bot_token "111:AAA" → Client A's workspace      │
│ 3. Process: Message for Client A                            │
│ 4. Respond: Using Client A's bot token "111:AAA"           │
└─────────────────────────────────────────────────────────────┘

Message to Client B (same time):
┌─────────────────────────────────────────────────────────────┐
│ Telegram → Your Server                                      │
│ POST /api/webhooks/telegram/222:BBB                         │
│ Header: X-Telegram-Bot-Api-Secret-Token: abc123xyz         │
│ Body: {"message": {"text": "Hi there"}}                     │
│                                                              │
│ Your Server:                                                 │
│ 1. Verify: abc123xyz == TELEGRAM_SECRET_TOKEN ✅            │
│ 2. Lookup: bot_token "222:BBB" → Client B's workspace      │
│ 3. Process: Message for Client B                            │
│ 4. Respond: Using Client B's bot token "222:BBB"           │
└─────────────────────────────────────────────────────────────┘

Message to Client C:
┌─────────────────────────────────────────────────────────────┐
│ WhatsApp → Your Server                                      │
│ POST /api/webhooks/whatsapp/333                             │
│ Header: X-Hub-Signature-256: sha256=calculated_hash        │
│ Body: {"entry": [{"changes": [...]}]}                       │
│                                                              │
│ Your Server:                                                 │
│ 1. Verify: HMAC(body, WHATSAPP_APP_SECRET) == hash ✅      │
│ 2. Lookup: phone_number_id "333" → Client C's workspace    │
│ 3. Process: Message for Client C                            │
│ 4. Respond: Using Client C's access token                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Summary Table

| Secret Type | Scope | Count | Storage | Purpose |
|-------------|-------|-------|---------|---------|
| **TELEGRAM_SECRET_TOKEN** | Platform | 1 | GitHub Secrets | Verify webhook is from Telegram |
| **WHATSAPP_APP_SECRET** | Platform | 1 | GitHub Secrets | Verify webhook is from WhatsApp |
| **INSTAGRAM_APP_SECRET** | Platform | 1 | GitHub Secrets | Verify webhook is from Instagram |
| **Bot Tokens** | Per Client | Many | Database (encrypted) | Identify client & send responses |
| **Access Tokens** | Per Client | Many | Database (encrypted) | Identify client & send responses |
| **Phone Number IDs** | Per Client | Many | Database (encrypted) | Identify client |

---

## Why This Design?

### Security Benefits:
1. **Platform Verification**: Attackers can't send fake webhooks (they don't know your platform secret)
2. **Client Isolation**: Each client's credentials are encrypted separately
3. **No Credential Exposure**: Client credentials never leave your database
4. **Scalability**: Add unlimited clients without changing platform secrets

### Practical Benefits:
1. **Simple Setup**: Only 3 platform secrets to manage (not 3 × number_of_clients)
2. **Easy Rotation**: Rotate platform secret once, update all webhooks
3. **Multi-Tenant**: Perfect for SaaS - one platform, many clients

---

## Code Implementation

### Where Platform Secrets Are Used:

```python
# backend/app/services/webhook_security.py

def verify_telegram_secret(received_token: str) -> bool:
    """Verify webhook is from Telegram"""
    expected_token = settings.TELEGRAM_SECRET_TOKEN  # From GitHub Secrets
    return secrets.compare_digest(received_token, expected_token)

def verify_whatsapp_signature(payload: bytes, signature: str) -> bool:
    """Verify webhook is from WhatsApp"""
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),  # From GitHub Secrets
        payload,
        hashlib.sha256
    ).hexdigest()
    return secrets.compare_digest(signature, expected)
```

### Where Client Credentials Are Used:

```python
# backend/app/services/webhook_handlers.py

async def handle_telegram_webhook(payload, headers, bot_token):
    # Step 1: Verify platform (using GitHub Secret)
    incoming_secret = headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not verify_telegram_secret(incoming_secret):
        raise WebhookSecurityError("Invalid platform secret")
    
    # Step 2: Identify client (using bot_token from URL)
    channel = await db.execute(
        select(Channel).where(
            Channel.encrypted_config["bot_token"] == encrypt(bot_token)
        )
    )
    
    # Step 3: Process for this specific client
    workspace_id = channel.workspace_id
    # ... process message for this workspace
```

---

## FAQ

### Q: Do I need a different TELEGRAM_SECRET_TOKEN for each client?
**A: NO!** One TELEGRAM_SECRET_TOKEN for all Telegram clients.

### Q: Where are individual client credentials stored?
**A: In the database**, in the `channels` table, encrypted in the `encrypted_config` column.

### Q: How does the system know which client a webhook belongs to?
**A: From the URL path** - `/api/webhooks/telegram/{bot_token}` - the bot_token identifies the client.

### Q: What if I don't use Telegram/WhatsApp/Instagram yet?
**A: Don't add those secrets** - they're optional. Add them when you enable those channels.

### Q: Can I use the same Meta app secret for WhatsApp and Instagram?
**A: YES!** If you use the same Meta app for both, use the same secret for both.

---

## Deployment Checklist

### Required GitHub Secrets (11):
- [ ] VPS_HOST
- [ ] VPS_USER  
- [ ] VPS_PASSWORD
- [ ] DATABASE_URL
- [ ] JWT_SECRET_KEY
- [ ] ENCRYPTION_KEY
- [ ] OPENAI_API_KEY
- [ ] ANTHROPIC_API_KEY
- [ ] RESEND_API_KEY
- [ ] RESEND_FROM_EMAIL
- [ ] SUPER_ADMIN_EMAIL

### Optional GitHub Secrets (add when needed):
- [ ] TELEGRAM_SECRET_TOKEN - Generate with `openssl rand -hex 16`
- [ ] WHATSAPP_APP_SECRET - Get from Meta Developer Console
- [ ] INSTAGRAM_APP_SECRET - Get from Meta Developer Console

### Client Credentials (stored in database automatically):
- ✅ Handled by your application when clients create channels
- ✅ Encrypted automatically using ENCRYPTION_KEY
- ✅ No manual setup needed

---

## You're Ready to Deploy! 🚀

The architecture is already implemented in your code. Just add the GitHub Secrets and push to `main`!
