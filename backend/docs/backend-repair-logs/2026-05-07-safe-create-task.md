# §4.4 — safe_create_task: Background Tasks Must Not Share Request Sessions

## Problem

Seven call sites used the pattern:

```python
try:
    asyncio.create_task(some_coroutine(db=db, ...))
except Exception:
    pass
```

Two bugs in this pattern:

1. **Silent failures.** `asyncio.create_task()` itself almost never raises.  The
   `except Exception: pass` only catches the (theoretical) case where the task
   *cannot be created* — it does **not** catch exceptions raised *inside* the
   coroutine after the event loop schedules it.  A failed webhook delivery or
   CSAT push goes completely unlogged.

2. **Session lifetime violation in `generate_and_send_csat_prompt`.** This
   coroutine was passed the request-scoped `db: AsyncSession` and then called
   `await db.execute(...)` inside the background task.  The request handler
   might reach its `finally` / response-completion path — closing the session —
   before the task runs, resulting in:
   ```
   sqlalchemy.exc.InvalidRequestError: This session is closed
   ```
   `trigger_event` already fixed this in a prior commit (it ignores the `db`
   arg and opens its own session), but `generate_and_send_csat_prompt` had not
   been updated.

## Fix

### New utility: `app/utils/tasks.py`

```python
def safe_create_task(coro, *, name=None) -> asyncio.Task:
    async def _wrapper():
        try:
            await coro
        except Exception:
            logger.error("Background task %r raised an unhandled exception", name or ..., exc_info=True)
    return asyncio.create_task(_wrapper(), name=name)
```

All background fire-and-forget tasks now go through `safe_create_task`.
Errors appear in structured logs with the task name and full traceback.

### `csat_service.generate_and_send_csat_prompt`

Removed the `db: AsyncSession` parameter.  The function now opens its own
`AsyncSessionLocal()` context manager, identical to the pattern in
`outbound_webhook_service.trigger_event`.  The `select` import was moved
inside the function; the module-level `AsyncSession` import was dropped.

### Call sites updated (7 total)

| File | Event |
|---|---|
| `routers/contacts.py` | `contact.updated` |
| `routers/conversations.py` | `conversation.resolved`, `csat_prompt` |
| `routers/webchat.py` | `csat.submitted` |
| `services/escalation_router.py` | `conversation.escalated` |
| `services/message_processor.py` | `conversation.created`, `message.received` |

## Files Changed

- `backend/app/utils/tasks.py` (new)
- `backend/app/services/csat_service.py` — removed `db` param, open own session
- `backend/app/routers/contacts.py`
- `backend/app/routers/conversations.py`
- `backend/app/routers/webchat.py`
- `backend/app/services/escalation_router.py`
- `backend/app/services/message_processor.py`
