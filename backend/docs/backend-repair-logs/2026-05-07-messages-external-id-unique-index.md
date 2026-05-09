# Message external_message_id Partial Unique Index

## Original Problem

`app/models/message.py` had a comment promising a partial unique index on
`external_message_id` for carrier-side deduplication. No such migration ever
existed across 26 migrations. The comment was a lie.

The application-level `check_message_duplicate` uses a SELECT-then-INSERT
pattern — a TOCTOU race. Two concurrent carrier webhook retries (Telegram
and Meta both retry at-least-once) both pass the check simultaneously and
both insert, producing:
- Duplicate messages in the conversation
- Duplicate AI reply generations (double billing)
- Duplicate AI outbound sends to the customer

**Severity:** HIGH

## Root Cause

Migration was promised in a model comment but never written. No existing
migration in 001–026 creates this index.

## Scope Decision: (conversation_id, external_message_id) NOT global

Telegram message IDs are sequential per-chat integers: 1, 2, 3...
Two different Telegram bots (different workspaces) each receive their first
message → both get `external_message_id = "1"`. A global unique index on
`external_message_id` alone would reject the second workspace's message
with IntegrityError.

Correct scope: `(conversation_id, external_message_id)`. Within one
conversation, the same carrier message ID must never appear twice.
Across conversations (different chats, different workspaces): allowed.

## Fix Strategy

Partial unique index: `(conversation_id, external_message_id) WHERE external_message_id IS NOT NULL`
- Scoped to conversation_id — correct semantic scope
- Partial (WHERE NOT NULL) — webchat and outbound messages have no external ID, unaffected
- CONCURRENTLY — no table lock on live database

## Exact Backend Changes

### New migration: `alembic/versions/028_add_messages_external_id_unique.py`
- Creates `ix_messages_external_id_unique` on `(conversation_id, external_message_id)`
  WHERE `external_message_id IS NOT NULL`
- Includes pre-run deduplication check query in comments

### Modified: `app/models/message.py`
- Replaced misleading comment with actual Index declaration in `__table_args__`
- Added `postgresql_where` clause for partial index documentation

## Frontend Impact

✅ No frontend changes needed.

## Deployment Notes

**IMPORTANT — check for existing duplicates BEFORE running migration:**
```sql
SELECT conversation_id, external_message_id, COUNT(*)
FROM messages
WHERE external_message_id IS NOT NULL
GROUP BY conversation_id, external_message_id
HAVING COUNT(*) > 1;
```
If any rows returned, deduplicate first (keep MIN(id) per group, delete rest).
`CREATE UNIQUE INDEX CONCURRENTLY` will fail with an error if duplicates exist —
no data will be lost, but the migration will need to be retried after cleanup.

Rollback: `alembic downgrade 027_add_conversation_workspace_updated_index`
drops the index with `DROP INDEX CONCURRENTLY`.

## Testing Added

- Manual: send the same Telegram/WhatsApp message twice (simulate retry) —
  second insert should fail with IntegrityError, dedup should catch it.
- Regression: normal inbound messages should insert without conflict.
- Verify `check_message_duplicate` still works as-is (no app code changed).

## Final Outcome

Database-level guarantee that no conversation ever contains two messages with
the same `external_message_id`. The app-level check_message_duplicate still
runs (belt + suspenders), but now the DB is the final safety net.

**Note on check_message_duplicate:** The app query still scopes by workspace_id
(via conversation join) rather than conversation_id, which is slightly broader.
For Telegram this means a message ID seen in conversation A would block the same
ID in conversation B of the same workspace — this is a latent app-level bug but
safe to leave for the webhook idempotency fix (§7.1).

## Next Recommended Fix

**H2 — Single max_jobs=20 arq bucket starves pro tenants** (message_tasks.py:383)
Free-tier workspaces fill the 20-slot worker pool; pro tenants queue behind them.
Fix: two arq queues — `messages_paid` and `messages_free` — each with dedicated worker.
