# Inbound Webhook Signature Enforcement (Telegram / WhatsApp / Instagram)

## Original Problem

`webhook_handlers.py` verified signatures only when the header was PRESENT:
```python
if secret_token:          # Telegram
if signature:             # WhatsApp
if signature:             # Instagram
```

A forged request without the signature header entirely bypassed all verification
and went straight to the message pipeline. The attacker only needed the webhook URL.

`webhook_security.py` was already correctly implemented with HMAC-SHA256 for all
three providers — it just wasn't being enforced.

**Severity:** HIGH — forged messages trigger billing, AI replies, escalations

## Root Cause

Optional-header guard pattern (`if header:`) instead of mandatory enforcement
when the secret is configured in the environment. The security module existed
but was effectively opt-in per request.

## What Was Already There (Good)

- `app/services/webhook_security.py` — complete HMAC-SHA256 verification for all
  three providers, with timing-safe comparison via `secrets.compare_digest`
- `WebhookHandlers` correctly imported `verify_webhook_signature`
- Resend and Razorpay webhooks were already correctly enforcing signatures

## Fix Strategy

Enforce headers when the corresponding env var is set:
- `TELEGRAM_SECRET_TOKEN` configured → `X-Telegram-Bot-Api-Secret-Token` required
- `WHATSAPP_APP_SECRET` configured → `X-Hub-Signature-256` required
- `INSTAGRAM_APP_SECRET` configured → `X-Hub-Signature-256` required

Backward compatible: if env var is not configured, behavior is unchanged
(verification skipped). This avoids breaking deployments that haven't yet
called `setWebhook` with a secret_token.

## Exact Backend Changes

**Modified: `app/services/webhook_handlers.py`**

1. Added `from app.config import settings` import
2. `handle_telegram_webhook`: replaced `if secret_token:` with
   `if settings.TELEGRAM_SECRET_TOKEN: [require header, then verify]`
3. `handle_whatsapp_webhook`: replaced `if signature:` with
   `if settings.WHATSAPP_APP_SECRET: [require header, then verify]`
4. `handle_instagram_webhook`: replaced `if signature:` with
   `if settings.INSTAGRAM_APP_SECRET: [require header, then verify]`

No new files. No DB changes. No API changes.

## Frontend Impact

✅ No frontend changes needed.

## Deployment Notes

**BEFORE DEPLOYING — verify all three env vars are set and match what was
registered with each provider:**

```bash
# Confirm env vars are set
echo $TELEGRAM_SECRET_TOKEN      # must match what was passed to setWebhook
echo $WHATSAPP_APP_SECRET        # must match app secret in Meta Developer Console
echo $INSTAGRAM_APP_SECRET       # must match app secret in Meta Developer Console
```

If any secret is set but the provider wasn't registered with that secret:
1. Either unset the env var (reverts to unverified, temporary)
2. Or re-register the webhook with the correct secret_token

Rolling restart of backend containers picks up the change.
Rollback: revert the 6 changed lines in `webhook_handlers.py`.

## Testing Added

- Manual: POST to `/webhooks/telegram/{token}` without `X-Telegram-Bot-Api-Secret-Token`
  header — should be swallowed (200 returned, pipeline not run, error logged).
- Manual: POST with wrong signature — same result.
- Manual: POST with correct signature — should process normally.
- Regression: all existing channel webhook flows should work with correct signature.

## Remaining Gaps

- §5.5 — `verify_resend_signature` swallows all exceptions and returns False
  (should only catch expected exceptions, let others propagate)
- §7.3 — Razorpay `subscription.activated` is not idempotent (duplicate events
  re-run the tier-update logic)
- §7.1 — Inbound webhooks still run synchronously, not enqueued to arq
  (this is the next critical fix for carrier retry deduplication)

## Next Recommended Fix

**H4 — Rate limiter stores timestamps in Postgres ARRAY**
`app/services/rate_limiter.py` appends to a Postgres ARRAY column on every
request — write storm under load. Replace with Redis INCR/EXPIRE.
