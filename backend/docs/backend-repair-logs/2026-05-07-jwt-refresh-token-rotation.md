# §5.2 — JWT: Short-Lived Access Tokens + Refresh Token Rotation

## Problem

Access tokens had a 7-day expiry with no refresh token rotation:
- A stolen AT gave an attacker 7 days of access with no way to detect reuse
- The `/refresh` endpoint accepted the AT itself as proof-of-identity and
  re-issued a new AT — this is not rotation, it is indefinite extension
- `JWT_EXPIRE_MINUTES = 10080` (7 days) meant the AT blocklist TTL was also
  7 days, keeping revoked tokens in Redis for longer than necessary

**Severity:** HIGH for security. Long-lived credentials make session hijacking
trivially exploitable.

## Fix

### Access token expiry: 7 days → 15 minutes
`JWT_EXPIRE_MINUTES` default changed from 10080 to 15 in `config.py`.
`JWT_REFRESH_EXPIRE_DAYS = 7` added for the new refresh token.

### Opaque refresh token (new: `app/services/refresh_token_service.py`)
- `create_refresh_token(user_id, email, role, workspace_id) → str`
  Generates a UUID4, stores claims JSON in Redis under `rt:{uuid}` with a
  7-day TTL, returns the UUID (the opaque token the client stores).

- `use_refresh_token(rt_id) → Optional[dict]`
  Atomically reads and deletes the Redis key. Returns claims on success, None
  if the key is missing or expired. Since the key is deleted before returning,
  a replayed token (from a stolen copy) returns None — the legitimate client
  has already consumed and rotated it.

- `revoke_refresh_token(rt_id) → None`
  Unconditional delete (called at logout). Swallows its own Redis errors to
  avoid masking the original logout flow.

### AT payload: `"rt"` claim
`create_access_token` gains an optional `refresh_token_id` parameter. When
provided, the AT payload includes `"rt": "<rt_uuid>"`. This lets `/logout`
revoke both tokens from a single bearer AT without requiring the client to
send the RT separately.

### `/refresh` endpoint (rotation)
Old behaviour: accepted the AT, decoded it, re-issued a new AT.
New behaviour: accepts `{ "refresh_token": "<uuid>" }`, calls
`use_refresh_token` (which atomically deletes the old RT), issues a new AT +
a new RT, returns both. The old RT is dead after one use.

### `/logout` endpoint
Now also reads `payload["rt"]` and calls `revoke_refresh_token` so the RT is
dead immediately, not left alive until its 7-day TTL.

### Schema changes
- `AuthResponse`: adds `refresh_token: str`
- `TokenRefreshRequest`: `token` field → `refresh_token`
- `TokenRefreshResponse`: adds `refresh_token: str`

## Files Changed

- `app/config.py`
- `app/schemas/auth.py`
- `app/services/auth_service.py`
- `app/services/refresh_token_service.py` (new)
- `app/routers/auth.py`

## Frontend Impact

See `docs/frontend-changes/2026-05-07-refresh-token-rotation.md`.
`POST /api/auth/refresh` request body is a breaking change.

## Deployment Notes

- No database migration required
- Redis: refresh token keys are `rt:{uuid}` with 7-day TTL — self-cleaning
- Existing 7-day JWTs remain valid until natural expiry. Users are not force-
  logged-out; they get a 15-min AT + RT on their next login
- Set `JWT_EXPIRE_MINUTES=15` in production `.env` (already the new default)

## Testing Checklist

- [ ] Login — verify response includes both `access_token` and `refresh_token`
- [ ] Wait 15 min (or set `JWT_EXPIRE_MINUTES=1`) — verify AT is rejected
- [ ] Call `/refresh` with old RT — verify new AT + new RT returned
- [ ] Call `/refresh` again with the OLD RT — verify 401 (rotation working)
- [ ] Logout — verify old RT is gone from Redis (`GET rt:<uuid>` returns nil)
- [ ] Replay old RT after logout — verify 401
