# /conversations list endpoint — N+1 fix via denormalized counters + batched last-message

PR5 of the Tier 1 scalability fix series. Adds two denormalized columns to `conversations` (backfilled in migration 034), rewrites the message-insert paths to maintain them, and replaces the `/conversations` list endpoint's per-row last-message + count subqueries with a single batched `DISTINCT ON` query. Net query count per request: **1 + 2*limit → 2**.

## Problem

Severity: **Critical** — the highest-traffic dashboard endpoint was doing 101 SQL queries per request at default `limit=50`.

The list endpoint at [app/routers/conversations.py:179-204](backend/app/routers/conversations.py#L179) issued, inside the `for conv in conversations:` loop:

```python
# Per-row last-message fetch
last_msg_result = await db.execute(
    select(Message)
    .where(Message.conversation_id == conv.id)
    .order_by(Message.created_at.desc())
    .limit(1)
)
...
# Per-row count
msg_count_result = await db.execute(
    select(func.count(Message.id)).where(Message.conversation_id == conv.id)
)
```

At `limit=50`: 1 outer list + 50 last-message + 50 count = **101 queries**.

Dashboard polling pattern: ~100 concurrent users × 1 list refresh / 10 s × 101 queries = **~1010 q/s** sustained — most of it indexed but every query is still a network round-trip eating a pool connection and ~2 ms of latency.

## Root cause

Two distinct N+1 patterns piled into one endpoint:

1. **Last message body**: the response payload includes a preview of the most recent message per conversation. Each was fetched per row.
2. **Message count**: also returned per row; computed via `COUNT(*)` per row.

The original implementation worked correctly but never scaled. The fix is to denormalize *just enough* to eliminate the per-row queries, while keeping write-side complexity bounded.

## Fix

### Denormalization — migration 034

Two new columns on `conversations`:

| Column | Type | Default | Why |
|--------|------|---------|-----|
| `last_message_at` | `timestamptz NULL` | — | enables the new compound index for `ORDER BY recency`; sanity-check anchor for the read path |
| `message_count` | `integer NOT NULL` | `'0'` server-side | direct read; eliminates the per-row `COUNT(*)` |

Backfill: a single `UPDATE … FROM (SELECT … GROUP BY conversation_id)`. Lock behavior, expected runtime, and abort criteria are documented in the migration docstring.

New index:

```sql
CREATE INDEX ix_conversations_workspace_lastmsg
  ON conversations (workspace_id, last_message_at DESC);
```

The migration is rollback-clean (drop index + drop both columns).

### Maintain at every Message INSERT site (5 of them)

The model declares both columns ([app/models/conversation.py](backend/app/models/conversation.py)). Every Message insert site now bumps the parent conversation's counters:

| Site | File:function | Approach |
|------|---------------|----------|
| 1 | [message_processor.py:create_message](backend/app/services/message_processor.py) | Conversation row not loaded — issue `UPDATE conversations SET …` |
| 2 | [escalation_router.py:create_escalation_message](backend/app/services/escalation_router.py) | Same |
| 3 | [escalation_router.py:send_customer_acknowledgment](backend/app/services/escalation_router.py) | Same |
| 4 | [conversation_manager.py:send_agent_message](backend/app/services/conversation_manager.py) | Conversation already in session — set attributes on the loaded ORM object |
| 5 | [conversation_manager.py:send_owner_message](backend/app/services/conversation_manager.py) | Same |

For sites 1–3, the bump uses a SQL-level UPDATE:

```python
await self.db.execute(
    _sa_update(Conversation)
    .where(Conversation.id == conversation_id)
    .values(
        last_message_at=func.now(),
        message_count=Conversation.message_count + 1,
        updated_at=func.now(),
    )
)
```

For sites 4–5, where the conversation is already loaded into the session, the bump is a Python-side attribute assignment (SQLAlchemy will emit the UPDATE on commit, avoiding any in-memory-vs-DB conflict):

```python
_now = datetime.now(timezone.utc)
conversation.updated_at = _now
conversation.last_message_at = _now
conversation.message_count = (conversation.message_count or 0) + 1
```

Both shapes are atomic within the existing per-message transaction. The increment uses `Conversation.message_count + 1` (SQL-level) at sites 1–3 to be concurrency-safe against parallel inserts on the same conversation; sites 4–5 are inherently single-actor (one agent / one owner sending one message at a time per conversation), so a Python-side `+1` is safe.

### Read path — `/conversations` list endpoint

Replaced the per-row loop with one batched `DISTINCT ON (conversation_id)` query for last-message bodies, and reads `message_count` directly from the denormalized column:

```python
last_msg_rows = await db.execute(
    select(Message)
    .where(Message.conversation_id.in_(conv_ids))
    .order_by(Message.conversation_id, Message.created_at.desc())
    .distinct(Message.conversation_id)
)
last_msg_by_conv = {m.conversation_id: m for m in last_msg_rows.scalars().all()}
...
message_count=conv.message_count or 0,   # ← from denormalized column
```

Net effect: **101 queries → 2 queries** per `/conversations` list request.

## Why this approach

### Why two columns, not three (or zero)

The audit's denormalization target was `last_message_at` + `message_count`. Two alternatives were considered:

- **Full denormalization** (`last_message_id`, `last_message_preview`, `last_message_role`, `last_message_extra_data`, plus the two above): kills the batched DISTINCT-ON query entirely, but adds 4–5 fields to maintain at every Message insert. Cost-benefit was poor — DISTINCT-ON over a `WHERE conversation_id IN (…)` set is fast on the existing `(conversation_id, created_at)` index.
- **Zero denormalization** (just batch the count too): possible via `SELECT conversation_id, COUNT(*) FROM messages WHERE conversation_id IN (...) GROUP BY conversation_id` — but then every read pays an aggregate. `message_count` is read on every dashboard refresh; the write-side increment is sub-microsecond.

Two columns + 1 batched query is the minimum that takes the endpoint from 101 to 2 queries.

### Why in-transaction increment, not a trigger

A Postgres `AFTER INSERT` trigger on `messages` would be tidier but adds operational complexity (now the schema has hidden behavior). The five INSERT sites are all in the same codebase, well-bounded, and easy to grep. Trigger remains an option as a belt-and-braces follow-up if a new INSERT site ever lands without the bump.

### Why same-migration backfill, not a deferred backfill script

This matches the codebase pattern (recent migrations don't use CONCURRENTLY because the deploy already has a maintenance window). The single `UPDATE … FROM (GROUP BY)` is one statement, fast enough on chaai's current scale. If `messages` ever grows past the migration's reasonable runtime budget, a follow-up migration can defer the backfill to a script + add NOT NULL afterward. The current scale doesn't justify the extra ceremony.

## Verification

### Migration
- `alembic upgrade head` then verify: `SELECT COUNT(*) FROM conversations WHERE message_count = 0 AND id IN (SELECT DISTINCT conversation_id FROM messages);` — expect `0` (every conversation with messages got a non-zero count).
- `\d conversations` confirms both new columns + `ix_conversations_workspace_lastmsg` index.
- `alembic downgrade -1` cleanly removes both columns + the index.

### Write path
- Send a webchat message: confirm `conversations.message_count` increments by 1 and `last_message_at` updates.
- Trigger an escalation (causes 2 system messages in quick succession): confirm count goes up by 2.
- Send an agent message from the dashboard: confirm the in-memory bump path works (count increments, no SQLAlchemy "stale data" warnings).

### Read path
- Hit `/conversations?limit=50` with SQLAlchemy echo enabled or `pg_stat_statements`. Expect exactly 2 user-visible queries beyond the manager's `get_workspace_conversations` (which itself emits the outer list query + its eager loads).
- Compare `message_count` returned by the endpoint vs `SELECT COUNT(*) FROM messages WHERE conversation_id = '…'` for several rows — must agree.

### Tests
- Existing test suite in [backend/tests/test_workspace_owner_api.py](backend/tests/test_workspace_owner_api.py) and [backend/tests/test_user_flow.py](backend/tests/test_user_flow.py) covers the conversation list endpoint — they pass without modification because the response shape is unchanged.
- Parse check on all 6 modified files — clean.

## Migration deployment notes

The backfill `UPDATE` issues one row update per conversation that has at least one message. Estimate: O(messages) sequential scan + GROUP BY + N indexed conversation row updates. On a ~10M-message workspace this is single-digit minutes; on a fresh / small DB it's seconds.

If the operator estimates the backfill exceeds the deploy window:

1. Skip running the migration in this deploy.
2. Branch a follow-up migration that adds the columns NULL-only (no backfill), and a code patch that reads `conv.message_count or <compute on the fly>` until backfill completes.
3. Run the backfill as a separate idempotent script (`UPDATE conversations WHERE last_message_at IS NULL …`) in batches of 10k.
4. Land a third migration that flips `message_count` to NOT NULL once backfill is verified complete.

The current migration is the "happy path"; the above is the documented escape.

## Files Changed

**New (1):**
- `backend/alembic/versions/034_add_conversation_denorm.py`

**Modified (5):**
- `backend/app/models/conversation.py` — declare `last_message_at` + `message_count` + new index documentation.
- `backend/app/services/message_processor.py` — bump counters in `create_message`; added `func` to existing `from sqlalchemy import` line.
- `backend/app/services/escalation_router.py` — bump counters in `create_escalation_message` and `send_customer_acknowledgment`; added `update`, `func` imports.
- `backend/app/services/conversation_manager.py` — bump counters in `send_agent_message` and `send_owner_message` via attribute assignment on the loaded conversation object.
- `backend/app/routers/conversations.py` — replaced N+1 loop with one batched `DISTINCT ON` query + read `message_count` from the denormalized column.

## Related commits

(Single PR — commit SHA to be filled at merge.)

## Frontend impact

None. Response shape is unchanged — `message_count` and `last_message` fields are returned in the same format. Only the server's query plan and latency differ.

## Follow-ups

- (Belt-and-braces) Postgres `AFTER INSERT` / `AFTER DELETE` trigger on `messages` to maintain the denormalized counters as a second line of defense. Deferred until proven necessary — current INSERT sites are well-bounded and reviewed.
- The `/conversations/search` endpoint at [conversations.py:258](backend/app/routers/conversations.py#L258) still uses `COUNT(*)` over a subquery for `total_count` — separate fix (cursor pagination, audit §2.2).
- Backfill correctness audit script: a CI check that asserts `SUM(message_count) FROM conversations == COUNT(*) FROM messages` per workspace, sampled periodically.
- Tests that explicitly assert the query count on `/conversations` list (using SQLAlchemy event hooks) to lock in the 2-query budget.
