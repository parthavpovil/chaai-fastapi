# Password Reset Backend Implementation

**Date:** 2026-05-13  
**Feature:** PIN-based password reset with session revocation

## Database Changes

New columns added to `users` table via migration 032:

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `password_reset_pin_hash` | String | NULL | Bcrypt hash of 6-digit PIN |
| `password_reset_expires_at` | DateTime(TZ) | NULL | PIN expiry timestamp (10 min TTL) |
| `password_reset_last_sent_at` | DateTime(TZ) | NULL | Last PIN sent timestamp |
| `password_reset_sent_day` | Date | NULL | Day of last PIN send (for daily quota) |
| `password_reset_sent_count` | Integer | 0 | PINs sent today (max 2) |
| `password_reset_attempts` | Integer | 0 | Failed verification attempts (max 5) |

## Configuration

Environment variables in `app/config.py`:

- `PASSWORD_RESET_PIN_LENGTH`: 6 (digits)
- `PASSWORD_RESET_PIN_TTL_MINUTES`: 10
- `PASSWORD_RESET_RESEND_COOLDOWN_SECONDS`: 300
- `PASSWORD_RESET_MAX_DAILY_SENDS`: 2
- `PASSWORD_RESET_MAX_ATTEMPTS`: 5

## New Endpoints

### 1. POST `/auth/forgot-password`

Request the password reset PIN via email.

**Request:**
```json
{
  "email": "user@example.com"
}
```

**Response (Always 200):**
```json
{
  "message": "If an account exists, a PIN will be sent to the email address"
}
```

**Rate Limiting:**
- Per-email auth limit: 10 attempts per 5 minutes
- Daily limit: 2 PINs per calendar day
- Cooldown: 300 seconds between requests

**Behavior:**
- If user not found: Returns generic success (no enumeration)
- If user found: Generates 6-digit PIN, hashes with bcrypt (10 rounds), stores with 10-minute expiry, sends email
- Enforces daily and cooldown limits (429 if limits exceeded)

### 2. POST `/auth/verify-password-reset`

Validate the PIN received via email.

**Request:**
```json
{
  "email": "user@example.com",
  "pin": "123456"
}
```

**Response (200):**
```json
{
  "message": "PIN verified. Proceed to reset password.",
  "token": "temp-password-reset-token-uuid"
}
```

**Errors:**
- 400 `invalid_pin`: PIN incorrect, max 5 attempts per reset request
- 400 `pin_expired`: PIN expired (10-minute window)
- 404: User not found

**Behavior:**
- Validates PIN hash using bcrypt
- Checks expiry timestamp
- Tracks failed attempts (max 5, then blocks further attempts)
- Returns temporary token to proceed to reset endpoint

### 3. POST `/auth/reset-password`

Update password and revoke all active sessions.

**Request:**
```json
{
  "email": "user@example.com",
  "pin": "123456",
  "new_password": "SecurePassword123!"
}
```

**Response (200):**
```json
{
  "message": "Password updated. Please log in again."
}
```

**Errors:**
- 400 `invalid_pin`: PIN does not match stored hash
- 400 `pin_expired`: PIN expired
- 404: User not found

**Behavior:**
1. Validates PIN (hash, expiry, attempts)
2. Updates user password with bcrypt 12-round hash (truncated to 72 bytes)
3. Clears all password reset fields: `password_reset_pin_hash`, `password_reset_expires_at`, `password_reset_attempts`
4. **Revokes all active refresh tokens** for the user via `revoke_refresh_tokens_for_user(user_id)`
5. Returns success message; user must re-login with new password

## Updated Endpoints

### POST `/auth/login`

No changes to endpoint signature. Password validation uses same bcrypt comparison logic.

**Password Reset Impact:**
- After password reset and token revocation, user must provide new password at login
- All previous sessions invalid; existing access/refresh tokens rejected

## Session Revocation

**New Refresh Token Service Method:**

```python
async def revoke_refresh_tokens_for_user(user_id: str) -> None:
    """Revoke all refresh tokens for a user."""
    # Get all RT IDs for the user
    rt_ids = await redis_client.smembers(f"rt_user:{user_id}")
    
    # Delete all token data
    for rt_id in rt_ids:
        await redis_client.delete(f"rt:{rt_id}")
    
    # Delete user RT set
    await redis_client.delete(f"rt_user:{user_id}")
```

**Usage:**
- Called in `POST /auth/reset-password` after password update
- Ensures user cannot use old refresh tokens after password change
- Atomic operation: all user tokens deleted together

## Email Template

**File:** `app/services/email_service.py`

```python
send_password_reset_pin_email(to: str, pin: str, expires_in_minutes: int)
```

**Template:**
- Subject: "Password Reset PIN"
- Body: HTML with monospace PIN display, expiry time, security notice
- Tag: `[{"name": "category", "value": "password_reset"}]` for Resend categorization
- Sent via Resend API

## Testing Checklist

- [ ] Register user with email verification complete
- [ ] Click "Forgot Password"
- [ ] Request PIN (check rate limits and daily max)
- [ ] Receive email with PIN
- [ ] Enter correct PIN → success with temp token
- [ ] Enter wrong PIN → error message, attempt counter increments
- [ ] After 5 failed attempts → blocked from further tries
- [ ] Set new password
- [ ] Verify old refresh tokens invalidated (old token rejected at refresh endpoint)
- [ ] Login with new password → success with new tokens
- [ ] Verify PIN email not sent to disposable email domains

## Security Considerations

1. **Password Hashing:** Bcrypt 12 rounds with 72-byte truncation (follows industry standard)
2. **PIN Hashing:** Bcrypt 10 rounds (faster than password, still resistant to brute force)
3. **Rate Limiting:** 2 PINs per day, 5-minute cooldown, max 5 attempts per request
4. **Session Revocation:** All refresh tokens atomically deleted to force re-login
5. **No Email Enumeration:** Generic response always returned (no indication if user exists)
6. **PIN Expiry:** 10-minute window reduces exposure window
7. **Attempt Tracking:** Failed verifications tracked separately from sends to prevent false blocks

## No Bypasses

Unlike email verification (which super admins and agents bypass), password reset applies to **all users** including:
- Super admins
- Workspace owners
- Agents
- Any authenticated user

This ensures consistent security posture across all user types.

## Dependencies

- **bcrypt**: Password and PIN hashing (already in requirements.txt)
- **Resend API**: Email delivery
- **Redis**: Session revocation tracking via refresh token service
- **rate limiting**: Existing auth_rate_limit module
