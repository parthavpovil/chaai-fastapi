# Email Verification Required for Owner Signups

## Why This Changed
Owner accounts must now verify their email via a PIN before they can log in. This blocks disposable email domains and reduces spam signups.

## Backend Changes
- POST /api/auth/register now returns a pending verification response for non-superadmin signups.
- New endpoints:
  - POST /api/auth/verify-email
  - POST /api/auth/resend-verification
- POST /api/auth/login now returns 403 with code email_not_verified for unverified owners.
- Disposable email domains rejected for owner signup and agent invites.

## Frontend Changes Required

### Affected pages / components
- Registration page / RegisterForm
- Login page / LoginForm
- Agent invite form (owner UI)

### What must change
1. Registration flow
   - If /register returns RegistrationPendingResponse, show PIN entry UI.
   - Do not treat this as a successful login (no tokens in response).

2. Verify email
   - Call POST /api/auth/verify-email with { email, pin }.
   - On success, show confirmation and redirect to login.

3. Resend PIN
   - Call POST /api/auth/resend-verification with { email }.
   - Handle 429 errors (cooldown or daily limit) with a user-friendly message.

4. Login gating
   - If /login returns 403 with code email_not_verified, prompt the user to verify and offer to resend PIN.

5. Agent invite form
   - If /api/agents/invite returns 400 with "Disposable email addresses are not allowed", show a validation error.

## New Response Shapes

### POST /api/auth/register (verification required)
```json
{
  "message": "Verification required. Check your email for the PIN.",
  "email": "owner@company.com",
  "verification_expires_at": "2026-05-13T10:15:00+00:00"
}
```

### POST /api/auth/verify-email
Request:
```json
{ "email": "owner@company.com", "pin": "123456" }
```
Response:
```json
{ "message": "Email verified successfully" }
```

### POST /api/auth/resend-verification
Request:
```json
{ "email": "owner@company.com" }
```
Response:
```json
{ "message": "Verification PIN resent" }
```

### POST /api/auth/login (unverified)
```json
HTTP 403
{
  "detail": {
    "message": "Email not verified",
    "code": "email_not_verified"
  }
}
```

## UX Notes
- PIN length: 6 digits
- PIN TTL: 10 minutes
- Resend policy: max 2 per day, 5 minute cooldown

## Testing Checklist
- [ ] Register new owner -> expect verification pending response
- [ ] Enter valid PIN -> verify success -> login works
- [ ] Enter invalid PIN -> show error; stop after max attempts
- [ ] Resend PIN twice in a day -> third attempt gets 429
- [ ] Login with unverified owner -> 403 with code email_not_verified
- [ ] Agent invite with disposable email -> 400 error shown
