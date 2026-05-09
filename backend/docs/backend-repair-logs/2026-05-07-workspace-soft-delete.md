# Workspace Soft-Delete (Replace Hard-Delete Cascade)

## Original Problem

`admin_service.delete_workspace` called `await self.db.delete(workspace)`.
The Workspace model has `cascade="all, delete-orphan"` on 17 relationships:
channels, contacts, conversations, agents, documents, document_chunks,
usage_counters, tier_changes, canned_responses, assignment_rules,
outbound_webhooks, outbound_webhook_logs, api_keys, csat_ratings,
business_hours, flows, whatsapp_templates, broadcasts, ai_agents, email_logs.

One admin misclick = instant irrecoverable destruction of all customer data,
billing history, and audit trails. No recovery path except a DB backup restore.

**Severity:** HIGH for compliance and ops safety.

## Root Cause

No `deleted_at` column on workspaces. No soft-delete logic anywhere.
A single `db.delete()` call triggers a cascade that destroys 17 related tables.

## Fix Strategy

Add `deleted_at TIMESTAMPTZ NULL` to the workspaces table. Change
`delete_workspace` to stamp `deleted_at` instead of issuing `db.delete()`.
The cascade never fires; all child data is preserved.

Also:
- Filter `deleted_at IS NULL` in admin workspace list and stats queries
- Filter `deleted_at IS NULL` in auth middleware so JWTs for deleted workspaces
  are rejected (prevents stale token access after deletion)

A hard-delete reaper (cronjob) should eventually purge workspaces with
`deleted_at < NOW() - INTERVAL '30 days'` and their child rows.
That reaper is a future task — not in this sprint.

## Exact Backend Changes

### New migration: `alembic/versions/029_add_workspace_soft_delete.py`
- `ALTER TABLE workspaces ADD COLUMN deleted_at TIMESTAMPTZ NULL`
- Partial index `ix_workspaces_deleted_at` on `deleted_at WHERE deleted_at IS NOT NULL`
  (used by future reaper to find rows eligible for hard deletion)

### Modified: `app/models/workspace.py`
- Added `deleted_at = Column(DateTime(timezone=True), nullable=True)`
- Added `__table_args__` with the partial index declaration
- Added `is_deleted` property for convenience

### Modified: `app/services/admin_service.py`
- `delete_workspace`: replaced `db.delete(workspace) + commit` with
  `workspace.deleted_at = datetime.now(timezone.utc) + commit`
- `get_workspaces` list: added `.where(Workspace.deleted_at.is_(None))`
- `get_platform_stats` tier breakdown count: added `deleted_at IS NULL` filter
- `get_platform_stats` total workspace count: added `deleted_at IS NULL` filter
- `get_platform_stats` recent signups count: added `deleted_at IS NULL` filter

### Modified: `app/middleware/auth_middleware.py`
- `get_current_workspace`: added `Workspace.deleted_at.is_(None)` to WHERE clause
- `get_workspace_from_token`: added `Workspace.deleted_at.is_(None)` to WHERE clause

## Frontend Impact

⚠ Frontend changes required (minor)

### What changes
- `DELETE /api/admin/workspaces/delete` now returns 200 (soft-delete) as before
- Workspace disappears from admin list immediately after deletion ✅
- Users with JWTs for deleted workspaces will get 401 "Workspace not found or
  has been deleted" instead of the previous behavior (workspace still loaded)

### Frontend TODO
- Handle 401 with message "Workspace not found or has been deleted" gracefully
  — show a logout/redirect screen rather than a generic error
- No changes to the deletion UI itself (same request format, same 200 response)

### Frontend Documentation File
`/docs/frontend-changes/2026-05-07-workspace-soft-delete-auth.md`

### Backward Compatibility
Deletion API contract is unchanged. The only visible difference to users is
that logging in after workspace deletion shows a clearer error message.

## Testing Added

- Manual: delete a workspace via admin API → verify it disappears from admin list
- Manual: use a JWT from a deleted workspace → verify 401 is returned
- Manual: verify workspace data (conversations, messages) still exists in DB
  after soft-delete (no cascade occurred)
- Regression: normal workspace list and auth flows unaffected

## Deployment Notes

- Run `alembic upgrade head` — adds nullable column, safe online operation
- Rolling Gunicorn restart after migration
- Rollback: `alembic downgrade 028_add_messages_external_id_unique` removes the
  column. Any workspaces soft-deleted between migration and rollback will reappear.

## Future Work

1. Hard-delete reaper: scheduled job that runs `DELETE FROM workspaces WHERE
   deleted_at < NOW() - INTERVAL '30 days'` (with cascades re-enabled or explicit
   child-table cleanup)
2. Add `deleted_at` to users, documents, conversations, messages, agents for
   full soft-delete coverage across all entities
3. GDPR export endpoint: export all data for a workspace before deletion

## Next Recommended Fix

**H5 — Observability: DLQ + Sentry + structlog + request-id**
This is a multi-day sprint but the highest remaining production-readiness gap.
Recommend tackling as a dedicated sprint with these four sub-tasks in order:
1. RequestIDMiddleware + structlog
2. Sentry SDK init with before_send PII scrub
3. prometheus-fastapi-instrumentator
4. arq terminal failure → LPUSH dlq:messages
