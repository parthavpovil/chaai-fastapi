# §5.6 + §5.7 — Exception Detail Leakage + IDOR Safety

## §5.6 — 5xx Detail Sanitization

### Problem

`grep -rn 'detail=f"Failed.*str(e)"' app/routers/` returns ~40 occurrences of:

```python
except Exception as e:
    raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")
```

`str(e)` of an `asyncpg.IntegrityError`, `botocore.exceptions.ClientError`, or
SQLAlchemy exception can include:
- Table names, column names, constraint names
- Partial SQL text
- File paths from storage SDKs
- Occasionally data values

These are returned verbatim to the caller because the existing
`_http_exception_handler` passes `exc.detail` through for all status codes.

### Fix

`_http_exception_handler` in `main.py` now applies a gate on `status_code >= 500`:

```python
if exc.status_code >= 500:
    logger.error("HTTP %s: ... — %s", exc.status_code, ..., exc.detail)
    safe_detail = "Internal server error"
else:
    safe_detail = exc.detail
```

The real error message is logged with the request-id (already present from
§9.2 middleware) so on-call engineers can correlate.  The client only ever
receives `"Internal server error"` for any 5xx, regardless of what the route
handler included in the detail string.

This is a defense-in-depth fix — routers still log the cause via the
exception chain, and future routes that accidentally embed `str(e)` are
covered automatically.

---

## §5.7 — Centralized Ownership Check (`get_owned`)

### Problem

~50 hand-written `WHERE model.id = :id AND model.workspace_id = :ws_id`
clauses across routers.  Each one is correct today, but the pattern is fragile:
a new contributor adding `GET /api/widgets/{widget_id}` might write
`WHERE id = :id` and forget the workspace predicate, creating an IDOR.

### Fix

Added `app/utils/owned.py`:

```python
async def get_owned(model, resource_id, workspace_id, db) -> T:
    result = await db.execute(
        select(model)
        .where(model.id == resource_id)
        .where(model.workspace_id == workspace_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(404)
    return obj
```

A single query with both predicates ensures that a valid ID from workspace A
cannot be accessed by workspace B — both "not found" and "wrong workspace"
return 404 (no enumeration).

New routes should use:
```python
document = await get_owned(Document, document_id, current_workspace.id, db)
```

Existing routes are not mass-refactored in this PR (the audit confirmed they
are all correct today), but new code should use `get_owned` exclusively.

## Files Changed

- `backend/main.py` — `_http_exception_handler`: sanitize 5xx details
- `backend/app/utils/owned.py` (new) — `get_owned` helper
