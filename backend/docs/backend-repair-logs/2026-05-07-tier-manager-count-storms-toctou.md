# §3.4 + §3.5 — TierManager: COUNT(*) Storms and TOCTOU Quota Checks

## Problems

### §3.4 — Sequential COUNT(*) storms

`_get_current_usage` issued 4 sequential round-trips per call:

```python
await db.execute(select(func.count(Channel.id)) ...)     # 1
await db.execute(select(func.count(Agent.id)) ...)       # 2
await db.execute(select(func.count(Document.id)) ...)    # 3
await db.execute(select(UsageCounter.messages_sent) ...) # 4
```

Every "create channel / agent / document" path and every dashboard tier-info
request paid this cost. The first three are pure COUNT(*) queries that
Postgres can collapse into a single scan.

**Impact:** ~15–20 ms of pure query overhead per write, growing as the
`channels`, `agents`, and `documents` tables grow without supporting indexes.

### §3.5 — Check-then-create TOCTOU

All three create endpoints followed this pattern:

```python
await tier_manager.check_channel_limit(workspace_id)  # reads count → OK
# ← another request can also pass here ←
db.add(Channel(...))
await db.commit()                                      # both inserts succeed
```

A free-tier workspace with `channels=1` limit could end up with 2 channels
if two requests arrived within milliseconds of each other.

**Impact:** Exploitable by any user scripting their own dashboard calls.
Severity: MEDIUM.

## Fix

### `_get_current_usage` — combined query (§3.4)

Three `COUNT(*)` queries replaced with a single `SELECT (subq1), (subq2), (subq3)`:

```sql
SELECT
  (SELECT COUNT(id) FROM channels WHERE workspace_id = :ws),
  (SELECT COUNT(id) FROM agents   WHERE workspace_id = :ws AND is_active = TRUE),
  (SELECT COUNT(id) FROM documents WHERE workspace_id = :ws)
```

Round-trips: 4 → 2 (combined counts + monthly-messages lookup).

### `_check_create_limit` — SELECT FOR UPDATE (§3.5)

New internal method used by `check_channel_limit`, `check_agent_limit`,
`check_document_limit`:

1. `SELECT workspace ... WITH FOR UPDATE` — acquires a row-level lock.
2. Runs the specific resource COUNT.
3. Raises `TierLimitError` if `current >= limit`.

The lock is held by the implicit SQLAlchemy transaction until the calling
router calls `db.commit()` (which also commits the INSERT). Any second
concurrent request that reaches `_check_create_limit` for the same workspace
will block on the FOR UPDATE until the first transaction commits. At that
point it re-counts and sees the new row — correctly rejecting if the limit is
now reached.

### Call-path comparison

| Method | Before | After |
|---|---|---|
| `check_channel_limit` | `get_workspace_tier_info` → 4 queries, no lock | `_check_create_limit` → 2 queries, FOR UPDATE |
| `check_agent_limit` | same | same |
| `check_document_limit` | same | same |
| `get_workspace_tier_info` (dashboard) | 5 queries | 3 queries (1 workspace + 1 combined COUNT + 1 usage) |

## Files Changed

- `app/services/tier_manager.py`
  - `_get_current_usage`: 4 queries → 2
  - `_check_create_limit`: new method (SELECT FOR UPDATE)
  - `check_channel_limit`, `check_agent_limit`, `check_document_limit`: now delegate to `_check_create_limit`

## Testing Checklist

- [ ] Create a channel at the free-tier limit → second create returns 429/TierLimitError
- [ ] Fire two concurrent create-channel requests for a free-tier workspace → only one succeeds
- [ ] `get_workspace_tier_info` still returns correct counts for dashboard display
- [ ] Upgrading tier (workspace.tier changes) reflected in next limit check without cache
