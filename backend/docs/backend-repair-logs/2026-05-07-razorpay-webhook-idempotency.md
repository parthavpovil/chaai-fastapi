# §7.3 — Razorpay Webhook Idempotency

## Problem

The Razorpay webhook handler processed every POST unconditionally. Razorpay
retries events for up to 48 hours on any non-2xx response, and their
infrastructure can also deliver the same event multiple times in close
succession. Without deduplication, a single payment event could:

- Activate a subscription twice
- Cancel and re-cancel a subscription, producing duplicate state transitions
- Trigger downstream notifications (email, Slack) multiple times

**Severity:** HIGH for billing correctness.

## Fix

### Idempotency key via Redis SET NX EX

```
rzp_event:{event.id}  →  TTL 48 h (172 800 s)
```

Flow:
1. Extract `event.id` from the Razorpay payload.
2. `SET rzp_event:{id} 1 NX EX 172800` — atomically claim the key.
3. If `acquired == False` (key already exists) → return `{"status": "ok"}` immediately (duplicate, skip).
4. If Redis is unavailable → log warning and **proceed** (process over skip — avoids silent subscription loss).
5. If the handler raises an exception → **delete the key** before re-raising 500, so Razorpay can retry and re-claim the key.
6. On success → key stays set for 48 h; future duplicates are silently dropped.

### Error behaviour

| Outcome | HTTP response | Key state |
|---|---|---|
| Duplicate event | 200 `{"status":"ok"}` | Unchanged (existing key) |
| Redis unavailable | 200 (proceeds without dedup) | No key written |
| Handler exception | 500 | Key deleted (retry allowed) |
| Success | 200 `{"status":"ok"}` | Key retained 48 h |

Returning 500 on handler failure is intentional — Razorpay only retries on
non-2xx, so we must return 500 (not 200) to signal "please try again."

### `_RZP_EVENT_TTL`

`172_800` seconds = 48 hours, matching Razorpay's maximum retry window.
Events older than 48 hours will never be retried so keeping the key longer
wastes Redis memory.

## Files Changed

- `app/routers/webhooks.py` — `razorpay_webhook()` rewritten with idempotency logic

## Testing Checklist

- [ ] Send a Razorpay `subscription.activated` event → subscription activates once
- [ ] Replay the same event (same `event.id`) → returns 200, no second activation
- [ ] Kill Redis, send event → processes normally (fallback path)
- [ ] Simulate handler exception → returns 500, idempotency key deleted, second POST processes
- [ ] Verify key TTL is ≤ 172800 s in Redis after successful processing
