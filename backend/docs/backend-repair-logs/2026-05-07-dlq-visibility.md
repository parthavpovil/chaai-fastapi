# §8.3 — DLQ Visibility: Admin Endpoints + List Cap

## Problem

`_push_dlq()` already wrote terminal arq failures to `dlq:messages` but:

1. **No visibility.** There was no API to read the list.  Operators had no way
   to discover permanent failures short of `redis-cli lrange dlq:messages 0 -1`.
2. **Unbounded growth.** `LPUSH` with no `LTRIM` lets the list grow forever if
   failures are frequent.

## Fix

### `message_tasks.py` — cap list at 1000 entries

After each `LPUSH`, `LTRIM dlq:messages 0 999` keeps only the most recent
1000 entries, preventing unbounded memory growth.

### `routers/admin.py` — two new super-admin endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/admin/dlq?limit=50` | List the most recent DLQ entries (newest first) |
| `DELETE` | `/api/admin/dlq` | Clear the entire DLQ list |

Response format for `GET`:
```json
{
  "total": 3,
  "returned": 3,
  "entries": [
    {
      "message_id": "...",
      "conversation_id": "...",
      "workspace_id": "...",
      "error": "...",
      "failed_at": "2026-05-07T12:00:00+00:00"
    }
  ]
}
```

Both endpoints require `require_super_admin` authentication, consistent with
all other `/api/admin/` routes.

## Files Changed

- `backend/app/tasks/message_tasks.py` — `_push_dlq`: added `LTRIM` cap;
  exported `DLQ_KEY` constant
- `backend/app/routers/admin.py` — `GET /api/admin/dlq`, `DELETE /api/admin/dlq`
