# arq Queue Split: Paid vs Free Tier Workers

## Original Problem

Single `MessageWorkerSettings` with `max_jobs = 20` and one shared queue.
Per-workspace concurrency semaphore limits each workspace's concurrent jobs,
but the pool ceiling is shared across all tiers.

Failure mode: 10 free-tier workspaces × 2 concurrent = 20 slots → pro tenants
queue behind free-tier workspaces indefinitely. Revenue-inverted SLA.

**Severity:** HIGH

## Root Cause

Single arq worker class, single queue, no tier isolation. The per-workspace
semaphore protects individual workspaces from each other but does not protect
paid tenants from aggregate free-tier load.

## Fix Strategy

Split into two queues and two worker containers:
- `messages_paid` — starter / growth / pro tenants, `max_jobs = 10`
- `messages_free` — free tier, `max_jobs = 10`

`enqueue_message_job` now accepts a `tier` parameter and routes to the correct
queue. Paid tenants get a guaranteed 10-slot pool that free tenants cannot touch.

The per-workspace concurrency semaphore continues to apply on top of the pool
isolation (belt and suspenders).

## Exact Backend Changes

### `app/tasks/message_tasks.py`
- Added `QUEUE_PAID = "messages_paid"` and `QUEUE_FREE = "messages_free"` constants
- Added `_FREE_TIERS = frozenset({"free"})` for routing decision
- Added `tier: str = "free"` parameter to `enqueue_message_job`
- Routes enqueue to `_queue_name=QUEUE_PAID` or `QUEUE_FREE` based on tier
- Replaced `MessageWorkerSettings` with `PaidMessageWorkerSettings` and
  `FreeMessageWorkerSettings`, each with `queue_name` set appropriately
- Kept `MessageWorkerSettings = FreeMessageWorkerSettings` as backward-compat alias

### `app/routers/webchat.py`
- Added `workspace_tier` lookup (single `SELECT Workspace.tier WHERE id = ...`)
  before the `enqueue_message_job` call
- Passes `tier=workspace_tier` to `enqueue_message_job`

### `app/tasks/reconciliation.py`
- Added `JOIN workspaces w ON w.id = c.workspace_id` to `_ORPHAN_QUERY`
- Added `w.tier AS workspace_tier` to SELECT
- Passes `tier=row.workspace_tier or "free"` to `enqueue_message_job`

### `docker-compose.prod.yml`
- Renamed `message-worker` service → `message-worker-paid`
  (command: `PaidMessageWorkerSettings`)
- Added `message-worker-free` service
  (command: `FreeMessageWorkerSettings`)
- Both services have identical env vars (same image, different queue)

## Frontend Impact

✅ No frontend changes needed. Message processing is background; response
delivery via WebSocket is unchanged.

## Testing Added

- Manual: enqueue 12 free-tier jobs simultaneously (>10 slots) — verify paid
  jobs still process immediately without waiting for free queue to drain.
- Manual: verify `_ORPHAN_QUERY` still returns correct orphaned messages after
  the workspace JOIN is added.
- Regression: normal webchat message flow should be unaffected.

## Deployment Notes

**Transition risk:** Jobs currently in the old default arq queue (`arq:queue`)
will NOT be picked up by the new workers (which poll `messages_paid` and
`messages_free`). The reconciliation sweeper re-enqueues any orphaned messages
within 60 seconds, so these jobs will be automatically recovered.

Deployment steps:
1. Deploy new image
2. `docker compose up -d --force-recreate message-worker-paid message-worker-free`
3. Remove old container: `docker compose rm -f message-worker` (if it still exists
   under the old name in your running stack)
4. Monitor reconciliation logs for any re-enqueued orphans

Rollback: revert docker-compose.prod.yml and message_tasks.py changes, redeploy
with original single `MessageWorkerSettings` and single worker container.

## Final Outcome

Paid tenants (starter/growth/pro) have a guaranteed 10-slot processing pool.
Free tenants have their own isolated 10-slot pool. Neither pool can starve the other.

**Remaining:** per-workspace semaphore release exception swallowing (§8.2) and
DLQ for terminal job failures (§8.3) are separate follow-up fixes.

## Next Recommended Fix

**H3 — No inbound webhook signature verification for Telegram / WhatsApp / Instagram**
Anyone who knows the webhook URL can POST forged messages that get processed end-to-end.
