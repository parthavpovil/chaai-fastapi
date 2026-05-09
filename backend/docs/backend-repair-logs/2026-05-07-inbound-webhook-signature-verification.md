# §5.4 + §5.5 — Inbound Webhook Signature Verification

## Problems

### §5.4 — No signature verification on Telegram, WhatsApp, Instagram

The three inbound channel webhook handlers accepted any POST from any source:

| Endpoint | Provider signature header | State before |
|---|---|---|
| `POST /webhooks/telegram/{bot_token}` | `X-Telegram-Bot-Api-Secret-Token` | Not checked |
| `POST /webhooks/whatsapp/{phone_number_id}` | `X-Hub-Signature-256` | Not checked |
| `POST /webhooks/instagram/{page_id}` | `X-Hub-Signature-256` | Not checked |

Anyone who knew (or guessed) the webhook URL could POST forged messages — fake
user messages, fake delivery receipts, arbitrary payloads — and they would be
processed end-to-end by the pipeline including RAG replies and billing counters.

Resend and Razorpay already had signature verification. These three did not.

**Severity:** HIGH.

### §5.5 — `verify_resend_signature` swallowed all exceptions

```python
except Exception as e:
    logger.error("Resend signature verification error: %s", e)
    return False
```

Any unexpected exception (broken config, import error, library bug) silently
returned `False`, making it look like an "invalid signature" rather than an
error. The root cause would be invisible in logs and Sentry.

**Severity:** MEDIUM.

## Fix

### New helpers in `app/routers/webhooks.py`

**`_verify_meta_signature(payload, sig_header, app_secret)`**

Meta (WhatsApp + Instagram) sends `X-Hub-Signature-256: sha256=<hex_digest>`.
The digest is HMAC-SHA256 of the raw request body keyed with the app secret.

```python
def _verify_meta_signature(payload: bytes, sig_header: str, app_secret: str) -> None:
    if not sig_header.startswith("sha256="):
        raise HTTPException(401, "Missing or malformed X-Hub-Signature-256")
    expected = sig_header[7:]
    computed = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, expected):
        raise HTTPException(401, "Invalid webhook signature")
```

**`_verify_telegram_secret_token(header_value, expected)`**

Telegram sends `X-Telegram-Bot-Api-Secret-Token` when the bot's webhook was
registered with the optional `secret_token` parameter. Constant-time compare
prevents timing-based extraction of the secret.

```python
def _verify_telegram_secret_token(header_value: str, expected: str) -> None:
    if not hmac.compare_digest(header_value, expected):
        raise HTTPException(401, "Invalid Telegram secret token")
```

### Verification call sites

Each handler verifies **before** delegating to `WebhookHandlers`:

```python
# Telegram
if settings.TELEGRAM_SECRET_TOKEN:
    _verify_telegram_secret_token(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""),
        settings.TELEGRAM_SECRET_TOKEN,
    )

# WhatsApp
if settings.WHATSAPP_APP_SECRET:
    _verify_meta_signature(payload, request.headers.get("X-Hub-Signature-256", ""),
                           settings.WHATSAPP_APP_SECRET)

# Instagram
if settings.INSTAGRAM_APP_SECRET:
    _verify_meta_signature(payload, request.headers.get("X-Hub-Signature-256", ""),
                           settings.INSTAGRAM_APP_SECRET)
```

**Fail-open when secret not configured:** If the env var is empty (e.g. an
existing deployment that hasn't set it yet), verification is skipped with no
change in behaviour.  Set the secret to enable enforcement.

### §5.5 — Narrowed exception catch in `verify_resend_signature`

Changed `except Exception` → `except (KeyError, ValueError, UnicodeDecodeError)`.
Unexpected exceptions (broken config, import error) now propagate to the global
exception handler and surface in Sentry rather than returning `False` silently.

## Configuration

| Setting | Used by | How to obtain |
|---|---|---|
| `TELEGRAM_SECRET_TOKEN` | `X-Telegram-Bot-Api-Secret-Token` | Set when calling `setWebhook` with `secret_token=<your_secret>` |
| `WHATSAPP_APP_SECRET` | `X-Hub-Signature-256` | Meta App Dashboard → App Secret |
| `INSTAGRAM_APP_SECRET` | `X-Hub-Signature-256` | Meta App Dashboard → App Secret (same app or separate) |

## Files Changed

- `app/routers/webhooks.py`
  - `verify_resend_signature`: narrowed exception catch (§5.5)
  - `_verify_meta_signature`: new helper
  - `_verify_telegram_secret_token`: new helper
  - `telegram_webhook`: calls `_verify_telegram_secret_token`
  - `whatsapp_webhook`: calls `_verify_meta_signature`
  - `instagram_webhook`: calls `_verify_meta_signature`

## Testing Checklist

- [ ] Telegram: POST without header when `TELEGRAM_SECRET_TOKEN` is set → 401
- [ ] Telegram: POST with wrong token → 401
- [ ] Telegram: POST with correct token → processes normally
- [ ] WhatsApp: POST without `X-Hub-Signature-256` when `WHATSAPP_APP_SECRET` is set → 401
- [ ] WhatsApp: POST with invalid HMAC → 401
- [ ] WhatsApp: POST with valid HMAC → processes normally
- [ ] Instagram: same three cases as WhatsApp
- [ ] All three: secret env var unset → verification skipped, existing behaviour preserved
- [ ] Resend: simulate broken config mid-verification → exception propagates (not silent False)
