# §7.1 — Inbound Channel Webhook Idempotency + Async Pipeline

## Problem

Telegram, WhatsApp, and Instagram webhook endpoints called `_run_message_pipeline()`
synchronously inside the HTTP request:

1. **Carrier retry → duplicate messages.** WhatsApp/Instagram expect a response
   within 5–10 seconds; Telegram within 60 seconds.  A RAG call takes 60–90 s.
   The carrier times out, marks delivery failed, and retries — processing the
   same message 2–4 times.

2. **No idempotency gate.** There was no check at the HTTP layer to detect
   duplicate deliveries.  The `external_message_id` unique DB constraint is a
   second line of defence, not a first.

## Fix

### 1. Redis idempotency gate — `_claim_inbound_message(provider, message_id)`

```python
key = f"inbound:{provider}:{external_message_id}"
acquired = await redis.set(key, "1", nx=True, ex=86_400)  # 24 h TTL
```

Called in all three webhook endpoints immediately after the handler returns
`status=success`.  If the key was already claimed the handler logs and returns
200 immediately.  Fail-open: Redis unavailability does not drop messages (the
DB unique constraint remains the authoritative dedup layer).

### 2. Background pipeline — `_run_pipeline_with_own_session`

A thin wrapper that opens a fresh `AsyncSessionLocal()` and calls
`_run_message_pipeline(db, ...)`.  Webhook endpoints now schedule this wrapper
via `safe_create_task(...)` and return 200 before the RAG pipeline starts:

```python
safe_create_task(
    _run_pipeline_with_own_session(...),
    name=f"pipeline.telegram.{external_msg_id}",
)
return {"ok": True}  # returned in < 50 ms
```

This meets Telegram's 60 s and Meta's 5–10 s response budget unconditionally.

## Files Changed

- `backend/app/routers/webhooks.py` — `_claim_inbound_message`,
  `_run_pipeline_with_own_session`, updated Telegram / WhatsApp / Instagram
  webhook endpoints
