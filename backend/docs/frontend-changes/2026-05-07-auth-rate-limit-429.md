# Auth Endpoints Now Return HTTP 429

## Why This Change Happened

Auth endpoints (`/login`, `/agent-login`, `/register`) had no rate limiting,
leaving them open to credential stuffing. A Redis-based rate limiter was added
that returns 429 after 10 failed attempts per email+IP within 5 minutes.

## Backend Changes

- `/api/auth/login` — may now return `429 Too Many Requests`
- `/api/auth/agent-login` — may now return `429 Too Many Requests`
- `/api/auth/register` — may now return `429 Too Many Requests`
- Response includes `Retry-After: N` header (seconds until retry is allowed)

## Frontend Changes Required

### Affected pages / components
- Login page / `LoginForm` component
- Agent login page / `AgentLoginForm` component
- Registration page / `RegisterForm` component
- Any shared `useAuth` hook or `authService` that calls these endpoints

### What must change
1. Detect `HTTP 429` response status in the auth API call handlers
2. Extract the `Retry-After` header value (seconds) from the response
3. Show a user-facing message: **"Too many attempts. Please wait N seconds."**
4. Optionally: disable the submit button and show a countdown timer using
   `Retry-After`

### Request payload — no change
### Response shape on success — no change

## Before vs After

### Old error responses from /login
```json
HTTP 401  { "detail": "Invalid email or password" }
HTTP 400  { "detail": "..." }
```

### New — also possible
```json
HTTP 429
Headers: Retry-After: 287
Body: { "detail": "Too many attempts. Try again in 287 seconds." }
```

## Migration Notes

- Old frontend code that only handles 401/400 will fall through to a generic
  error handler on 429 — this is acceptable short-term (user sees a generic
  error) but should be updated for a good UX.
- No breaking changes to successful login flow.

## Testing Checklist

- [ ] Submit login form 11 times in 5 minutes — 11th should show rate limit message
- [ ] Verify countdown / Retry-After is displayed to the user
- [ ] Verify normal login still works on attempts 1–10
- [ ] Verify the register form handles 429 with a clear message
- [ ] Verify agent login form handles 429 with a clear message

## Risk Notes

- If frontend does not handle 429, users will see a generic "something went wrong"
  message after being rate-limited, which is confusing but not broken.
- The rate limit resets automatically after 5 minutes — no manual intervention needed.
