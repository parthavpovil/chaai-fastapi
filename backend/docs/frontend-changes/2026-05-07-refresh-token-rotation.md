# Auth: Short-Lived Access Tokens + Refresh Token Rotation

## Why This Changed

Access tokens previously lived for 7 days. A stolen token gave an attacker 7
days of uninterrupted access. The fix introduces short-lived access tokens
(15 min) paired with a long-lived opaque refresh token (7 days) that rotates
on every use.

## What Changed in the API

### Login / Register responses (POST /api/auth/login, /register, /agent-login)

All three now return a `refresh_token` field alongside `access_token`:

```json
{
  "access_token": "<jwt — expires in 15 min>",
  "refresh_token": "<opaque UUID — expires in 7 days>",
  "token_type": "bearer",
  "user": { ... },
  "workspace": { ... }
}
```

### POST /api/auth/refresh — BREAKING CHANGE

**Before:**
```json
{ "token": "<current access token>" }
```
**After:**
```json
{ "refresh_token": "<opaque refresh token UUID>" }
```

**Response before:**
```json
{ "access_token": "<new jwt>", "token_type": "bearer" }
```
**Response after:**
```json
{
  "access_token": "<new jwt — expires in 15 min>",
  "refresh_token": "<new opaque UUID — old one is now invalid>",
  "token_type": "bearer"
}
```

### POST /api/auth/logout

No change to the request. Logout now also revokes the refresh token that was
linked to the access token at login time. Frontend does not need to send the
refresh token separately.

## What Frontend Must Do

### 1. Store the refresh token
Persist `refresh_token` from the login/register response alongside (or instead
of) the long-lived access token you stored before.

Recommended: `localStorage` or `sessionStorage` keyed by `"refresh_token"`.
Do NOT store it in a cookie accessible to JavaScript if you store the access
token there too — that defeats the purpose.

### 2. Implement proactive token refresh
The access token now expires in 15 minutes. Frontend must call
`POST /api/auth/refresh` before it expires.

Recommended pattern (interceptor):
- Decode the `access_token` JWT to read the `exp` claim
- Schedule a refresh ~2 minutes before expiry
- On 401 from any API call: attempt one refresh, retry the original request,
  then if still 401 → log the user out

### 3. Update the refresh call

Old:
```js
await api.post('/api/auth/refresh', { token: storedAccessToken })
```

New:
```js
const { access_token, refresh_token } = await api.post('/api/auth/refresh', {
  refresh_token: storedRefreshToken
})
// Store both new tokens; old refresh token is now invalid
```

### 4. Handle refresh token expiry
If `/api/auth/refresh` returns 401 (`"Invalid or expired refresh token"`), the
session has fully expired — log the user out and redirect to login.

## Migration Notes

- Existing 7-day JWTs issued before this change remain valid until their
  natural expiry. They carry no `"rt"` claim, so logout for those sessions
  only revokes the AT JTI (same as before).
- After expiry, users will be asked to log in again, at which point they
  receive the new short-lived AT + RT pair.
- No database migration required.

## Risk Notes

- If the frontend does not implement proactive refresh, users will be logged
  out every 15 minutes. Implement the refresh interceptor before deploying.
