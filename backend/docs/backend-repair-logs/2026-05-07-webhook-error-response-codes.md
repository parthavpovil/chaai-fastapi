# §7.2 — Webhooks Return Correct Status Codes on Error

## Problem

All three channel webhook handlers (Telegram, WhatsApp, Instagram) wrapped their
entire handler call in a single `except Exception` that logged the error and
returned 200 regardless. The Telegram handler even had an explicit comment:
`# Always return 200 to prevent Telegram retries`.

This caused two concrete problems:

1. **Silent message loss** — signature verification failures, malformed payloads,
   and unexpected exceptions all returned 200, telling the provider "message
   received". The provider stopped retrying, so the message was lost forever.

2. **Security failures indistinguishable from successes** — an attacker sending
   a forged webhook with the wrong signature received 200, making the endpoint
   appear to accept forged events from the outside (though they were logged and
   not processed internally).

**Severity:** HIGH for data integrity. Any DB hiccup during channel lookup would
silently drop inbound messages with no retry.

## Error Taxonomy

Not all errors warrant the same response:

| Error type | HTTP code | Reason |
|---|---|---|
| Missing/invalid signature | 400 | Permanent; retrying same payload won't fix it |
| Malformed JSON | 400 | Permanent; retrying same payload won't fix it |
| Channel not found / inactive | 200 | Permanent misconfiguration; stop retries silently |
| Unexpected DB / processing error | 500 | Transient; provider should retry |
| Pipeline error (after message stored) | 200 | Message in DB; retry would duplicate it |

The "channel not found → 200" rule is deliberate: the workspace admin deleted
or deactivated the channel. Returning 500 would cause Telegram to retry for
48 hours with no hope of success. Silent 200 is the correct no-op.

## Fix

### `app/services/webhook_handlers.py`

`WebhookProcessingError` gained a `status_code: int = 400` constructor argument.
Raise sites updated:

- Auth/parse failures: default 400 ✓ (no change needed)
- `"Channel not found or inactive"` (×3): `status_code=200`
- `"X webhook processing failed"` generic wraps (×3): `status_code=500`

### `app/routers/webhooks.py`

All three channel webhook handlers (`telegram_webhook`, `whatsapp_webhook`,
`instagram_webhook`) restructured from:

```python
try:
    result = await WebhookHandlers(db).handle_X_webhook(...)
    # process result ...
except Exception as e:
    logger.error(...)
return {"ok": True}  # always 200
```

to:

```python
try:
    result = await WebhookHandlers(db).handle_X_webhook(...)
except WebhookProcessingError as e:
    if e.status_code == 200:
        return {"ok": True}   # permanent no-op
    raise HTTPException(status_code=e.status_code, detail=str(e))
except Exception as e:
    logger.error("Unexpected error", exc_info=True)
    raise HTTPException(status_code=500, detail="Internal processing error")

# process result ...  (pipeline errors still return 200)
return {"ok": True}
```

Pipeline errors (after the handler returns `"success"` and message is stored)
are still caught and logged internally, returning 200. The message is in the DB
and the arq worker processes it asynchronously; retrying the webhook would create
a duplicate.

## Frontend Impact

None — these are inbound webhook endpoints not called by the frontend.

## Testing Checklist

- [ ] Send Telegram webhook with wrong `X-Telegram-Bot-Api-Secret-Token` — verify 400
- [ ] Send WhatsApp webhook with wrong `X-Hub-Signature-256` — verify 400
- [ ] Send to Telegram bot_token with no matching channel — verify 200 (silent no-op)
- [ ] Simulate DB error during channel lookup — verify 500
- [ ] Successful Telegram message — verify 200 and message appears in DB
