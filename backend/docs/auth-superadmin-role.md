# Auth Changes — `superadmin` JWT Role

**Branch:** main
**Date:** 2026-05-10
**Scope:** Add a third role `"superadmin"` to the JWT `role` claim, set automatically when the configured super-admin email logs in.

---

## Summary

Until now the JWT `role` claim only carried two values: `"owner"` or `"agent"`. The platform also has an out-of-band notion of "super admin" via `settings.SUPER_ADMIN_EMAIL`, but this was never reflected in the token — every super-admin login received `role="owner"` and downstream code had to re-check the email.

`POST /api/auth/login` now emits `role="superadmin"` in both the access token and refresh token claims when the authenticated user's email matches `SUPER_ADMIN_EMAIL` (case-insensitive). All other login paths and the existing `require_super_admin()` email check are unchanged.

No breaking changes. No DB migration. No new environment variables.

---

## What Changed

### 1. `POST /api/auth/login` — role resolution

**File:** [`backend/app/routers/auth.py`](../app/routers/auth.py) (`login_user()`)

Before issuing tokens, the role is computed from the user's email:

```python
role = "superadmin" if user.email.lower() == settings.SUPER_ADMIN_EMAIL.lower() else "owner"
```

The same `role` value is then passed into both `create_refresh_token(...)` and `auth_service.create_access_token(...)`. This replaces the previously hard-coded string `"owner"`.

The agent-block at the top of `/login` is preserved: a super-admin user is still rejected if they somehow have an active `Agent` row, and falls through normally otherwise.

### 2. `POST /api/auth/agent-login` — UNCHANGED

Agent login still issues `role="agent"` regardless of the email. This is intentional: superadmin status is granted only via the standard owner-style login. If the configured super-admin email is also linked to an active Agent record (an unusual configuration), `/agent-login` will still mint an agent token for them.

### 3. `POST /api/auth/register` — UNCHANGED

Registration always issues `role="owner"`. A super-admin must register first, then log in via `/login` to receive a superadmin token. Re-issuing the token on next login picks up the superadmin role without any data backfill.

### 4. `POST /api/auth/refresh` — preserves superadmin

Refresh tokens already carry the `role` claim verbatim through Redis ([`backend/app/services/refresh_token_service.py`](../app/services/refresh_token_service.py)). Token rotation preserves `role="superadmin"` end-to-end without any code change.

### 5. Permissions — unmasked for superadmin

[`backend/app/services/permission_service.py`](../app/services/permission_service.py) at `get_effective_permissions()` only applies the `AGENT_CEILING` mask when `role == "agent"`. Superadmin falls into the same `else` branch as owner and receives the full unmasked tier permissions for whatever workspace context is resolved. No code change was required here.

### 6. `auth_service.create_access_token()` — docstring

The docstring for the `role` parameter now reads `User role (owner | agent | superadmin)`. Validation logic is unchanged: `decode_access_token()` only requires `role` to be non-empty and accepts any string value.

---

## JWT Payload — Before vs After

### Before (super-admin email logging in)

```json
{
  "sub": "uuid-of-user",
  "email": "admin@yourdomain.com",
  "role": "owner",
  "workspace_id": "uuid-of-workspace-or-null",
  "exp": 1747862400,
  "iat": 1747861500,
  "jti": "uuid",
  "rt": "opaque-refresh-token-id"
}
```

### After (super-admin email logging in)

```json
{
  "sub": "uuid-of-user",
  "email": "admin@yourdomain.com",
  "role": "superadmin",
  "workspace_id": "uuid-of-workspace-or-null",
  "exp": 1747862400,
  "iat": 1747861500,
  "jti": "uuid",
  "rt": "opaque-refresh-token-id"
}
```

All other fields (and the token shape itself) are identical.

---

## Frontend / Consumer Impact

- Frontends that decode the access token can now read `role === "superadmin"` directly to gate super-admin-only UI, instead of fetching the user profile and comparing the email.
- The owner role detection logic (`role === "owner"`) **must be updated** anywhere it's used to also accept `"superadmin"` as an owner-like role for general workspace UX, OR consumers should explicitly branch on the new value. Otherwise super-admin sessions may appear "logged out of owner features" client-side.
- Existing super-admin admin endpoints (`/api/admin/*`) continue to work unchanged — `require_super_admin()` re-checks the email server-side, so no client change is needed for those endpoints.

---

## Files Touched

| File | Change |
|------|--------|
| `backend/app/routers/auth.py` | Imports `settings`; computes `role` in `login_user()` based on email |
| `backend/app/services/auth_service.py` | Docstring updated to list new role value |
| `backend/docs/auth-superadmin-role.md` | This changelog (new) |

## Files Explicitly NOT Touched

- `backend/app/routers/admin.py` — `require_super_admin()` keeps the existing email check. Both email-based and JWT-role-based super-admin sessions pass through unchanged.
- `backend/app/routers/admin_permissions.py` — same.
- `backend/app/middleware/auth_middleware.py` — `require_role()` already accepts arbitrary role strings.
- `backend/app/services/refresh_token_service.py` — generic `role: str` plumbing already round-trips the new value.
- No DB migration; the users table has no role column.

---

## How to Verify

1. **Owner login regression** — log in with a non-super-admin email; decoded token shows `"role": "owner"`.
2. **Superadmin login** — set `SUPER_ADMIN_EMAIL=foo@example.com`, register that user, log in via `/api/auth/login`, decode the access token, confirm `"role": "superadmin"`.
3. **Refresh preserves the role** — exchange the refresh token via `POST /api/auth/refresh`; the new access token is still `"role": "superadmin"`.
4. **Agent login unaffected** — agent login produces `"role": "agent"` regardless of email.
5. **Permissions unmasked** — for a super-admin who also owns a workspace, `get_effective_permissions(...)` returns the same flags as for an owner (no `AGENT_CEILING` mask applied).
6. **Existing admin endpoints still gate correctly** — call any `/api/admin/*` endpoint with the super-admin token; access is allowed via the existing email check.
7. **Case-insensitivity** — log in with the super-admin email in mixed case (e.g. `Admin@YourDomain.com`); token still resolves to `"role": "superadmin"`.
