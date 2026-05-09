# Workspace Deletion Now Soft-Deletes; Auth Error Message Updated

## Why This Change Happened

Workspace deletion previously hard-deleted all data instantly via a 17-table
cascade. It has been changed to soft-delete (sets `deleted_at` timestamp) to
preserve data for recovery and compliance.

## Backend Changes

- `DELETE /api/admin/workspaces/delete` — behaviour unchanged externally (returns 200)
  but now soft-deletes the workspace instead of destroying it permanently
- Workspace is excluded from admin list immediately after deletion
- Any JWT for a soft-deleted workspace now returns **401 Unauthorized**
  with message: `"Workspace not found or has been deleted"`

## Frontend Changes Required

### Affected components
- Auth error handler / interceptor (global axios/fetch error handler)
- Any page that makes authenticated requests (all authenticated pages)

### What must change
Handle 401 with the specific message `"Workspace not found or has been deleted"`:
- Show a clear message: **"This workspace has been deleted. Please contact support."**
- Log the user out and redirect to the login screen
- Do NOT show a generic "session expired" message — this is a workspace deletion,
  not a token expiry

### Request / response format — no change
### Deletion UI — no change (same request body, same 200 response)

## Before vs After

### Old 401 response (workspace not found)
```json
HTTP 401
{ "detail": "Workspace not found" }
```

### New 401 response (soft-deleted workspace)
```json
HTTP 401
{ "detail": "Workspace not found or has been deleted" }
```

## Migration Notes

- No breaking changes to the deletion flow
- The only new behavior: JWTs from deleted workspaces now get a cleaner 401
- Backward compatible: existing error handling that catches 401 generically
  will still log the user out, which is the correct behavior

## Testing Checklist

- [ ] Delete a workspace as super admin — verify it disappears from admin list
- [ ] Use a token from the deleted workspace — verify 401 is returned
- [ ] Verify the 401 message is shown clearly to the user (not generic error)
- [ ] Verify normal auth flows (login, token refresh) are unaffected

## Risk Notes

- Users with active sessions in a deleted workspace will get a 401 on their
  next API call. This is intentional — the workspace no longer exists for them.
