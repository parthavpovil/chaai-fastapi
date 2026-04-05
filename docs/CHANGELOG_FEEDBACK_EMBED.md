# Change: Embed Message Feedback in Conversation Response

## What Changed

Feedback (thumbs-up/down) for AI messages is now returned inline inside the `GET /api/conversations/{id}` response, instead of requiring a separate API call per message.

## Before

To display feedback state for a conversation with N messages, the frontend made **N + 1 API calls**:

```
GET /api/conversations/{id}
GET /api/conversations/{id}/messages/{msg1_id}/feedback
GET /api/conversations/{id}/messages/{msg2_id}/feedback
...
```

## After

A single call returns everything:

```
GET /api/conversations/{id}
```

Each message object now includes a `feedback` field:

```json
{
  "id": "uuid",
  "content": "How can I help you?",
  "role": "assistant",
  "sender_name": null,
  "created_at": "2024-01-01T00:00:01Z",
  "metadata": {},
  "feedback": {
    "id": "uuid",
    "message_id": "uuid",
    "rating": "positive",
    "comment": null,
    "created_at": "2024-01-01T00:00:05Z"
  }
}
```

`feedback` is `null` if no feedback has been submitted for that message.

## Removed Endpoint

`GET /api/conversations/{conversation_id}/messages/{message_id}/feedback` — **deleted**. No longer needed.

## Unchanged

`POST /api/conversations/{conversation_id}/messages/{message_id}/feedback` — works exactly as before.

## Files Modified

| File | Change |
|------|--------|
| `app/routers/conversations.py` | Added `feedback` field to `MessageResponse`; removed `get_ai_feedback` GET endpoint |
| `app/services/conversation_manager.py` | Eager-loads `ai_feedback` via chained `selectinload`; includes feedback in message dict |
