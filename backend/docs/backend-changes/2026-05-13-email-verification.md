# Email Verification + Disposable Email Blocking

## Summary
Owner signups now require email verification via PIN before login. Disposable email domains are blocked for owner signups and agent invites. Super admin and invited agents are exempt from verification.

## Database Changes
- New user fields:
  - email_verified (bool)
  - email_verification_pin_hash (string)
  - email_verification_expires_at (timestamp)
  - email_verification_last_sent_at (timestamp)
  - email_verification_sent_day (date)
  - email_verification_sent_count (int)
  - email_verification_attempts (int)
- Migration: 031_add_user_email_verification

## New/Updated Endpoints
- POST /api/auth/register
  - Now returns either AuthResponse (super admin) or RegistrationPendingResponse
  - RegistrationPendingResponse:
    - message
    - email
    - verification_expires_at

- POST /api/auth/verify-email
  - Request: { email, pin }
  - Response: { message }

- POST /api/auth/resend-verification
  - Request: { email }
  - Response: { message }
  - Rate limits: 2 per day, 5 minute cooldown, 429 on violation

- POST /api/auth/login
  - Now blocks unverified owners with 403 and code email_not_verified

## Verification Rules
- PIN length: 6 digits
- PIN TTL: 10 minutes
- Max invalid attempts: 5
- Resend policy: max 2 per day, 5 minute cooldown

## Bypass Rules
- Super admin (SUPER_ADMIN_EMAIL): skip verification
- Invited agents: created with email_verified = true

## Disposable Email Policy
- Disposable email domains rejected on owner signup and agent invite
- Source: disposable-email-domains blocklist
