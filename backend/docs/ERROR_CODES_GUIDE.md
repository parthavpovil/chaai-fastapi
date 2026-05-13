# Error Codes Reference Guide

This guide helps you identify and handle backend errors correctly in the frontend.

## Error Response Structure

All API errors now return a structured JSON response:

```json
{
  "error_code": "EMAIL_ALREADY_REGISTERED",
  "detail": "This email is already registered. Please log in or use a different email.",
  "error_type": "business_logic_error",
  "request_id": "a1b2c3d4-e5f6-7890",
  "timestamp": "2026-05-13T10:15:00Z"
}
```

### Fields
- **error_code**: Machine-readable error identifier (always UPPERCASE_WITH_UNDERSCORES)
- **detail**: Human-readable message to show to the user
- **error_type**: One of: `validation_error`, `business_logic_error`, `server_error`, `rate_limit`
- **request_id**: Tracking ID for debugging (include in support tickets)
- **timestamp**: When the error occurred (ISO 8601 format)

---

## POST /api/auth/register

### Success Cases
- **200** - Super admin registration with immediate login
- **200** - Regular user registration (returns RegistrationPendingResponse)

### User/Frontend Errors (4xx)

| Error Code | HTTP | Message | User Action |
|------------|------|---------|-------------|
| `DISPOSABLE_EMAIL` | 400 | "Please use a valid business email" | Use company email instead of Gmail, Outlook, etc. |
| `EMAIL_ALREADY_REGISTERED` | 400 | "This email is already registered. Please log in or use a different email." | Go to login page or try different email |
| `INVALID_INPUT` | 400 | Specific validation error details | Check input format (password ≥8 chars, valid email, business name ≤100 chars) |
| `RATE_LIMIT_EXCEEDED` | 429 | "Too many registration attempts. Please try again later." | Wait 5-15 minutes before trying again |

### Server Errors (5xx)

| Error Code | HTTP | Message | Issue Type |
|------------|------|---------|-----------|
| `EMAIL_SERVICE_FAILED` | 500 | "Failed to send verification email. Please try again or contact support." | Backend email service down |
| `INTERNAL_ERROR` | 500 | "An unexpected error occurred. Please try again or contact support." | Unknown backend error |

---

## POST /api/auth/verify-email

### Success Case
- **200** - "Email verified successfully"

### User/Frontend Errors (4xx)

| Error Code | HTTP | Message | User Action |
|------------|------|---------|-------------|
| `USER_NOT_FOUND` | 400 | "No pending verification found for this email. Please register first." | User is not registered |
| `PIN_INVALID` | 400 | "Invalid PIN. 4 attempts remaining." | Try again with correct PIN |
| `PIN_EXPIRED` | 400 | "Verification PIN has expired. Please request a new one." | Click "Resend PIN" button |
| `PIN_NOT_SENT` | 400 | "No verification PIN found. Please request a new PIN." | Click "Resend PIN" button |

### Rate Limit Errors (429)

| Error Code | HTTP | Message | User Action |
|------------|------|---------|-------------|
| `TOO_MANY_ATTEMPTS` | 429 | "Too many invalid attempts. Please request a new PIN." | Wait and request new PIN |
| `RATE_LIMIT_EXCEEDED` | 429 | "Too many verification attempts. Please try again later." | Wait 5-15 minutes |

---

## POST /api/auth/resend-verification

### Success Case
- **200** - "Verification PIN resent. Check your email."

### User/Frontend Errors (4xx)

| Error Code | HTTP | Message | User Action |
|------------|------|---------|-------------|
| `USER_NOT_FOUND` | 400 | "No account found with this email. Please register first." | User is not registered |
| `EMAIL_ALREADY_VERIFIED` | 400 | "Your email is already verified. You can log in now." | Redirect to login |

### Rate Limit Errors (429)

| Error Code | HTTP | Message | User Action |
|------------|------|---------|-------------|
| `DAILY_LIMIT_EXCEEDED` | 429 | "You can resend the PIN maximum 2 times per day. Please try again tomorrow." | Wait until next day |
| `RESEND_COOLDOWN` | 429 | "Please wait 245 seconds before requesting another PIN." | Wait specified time |
| `RATE_LIMIT_EXCEEDED` | 429 | "Too many resend requests. Please try again later." | Wait 5-15 minutes |

---

## Frontend Implementation Guidelines

### 1. Error Handling Pattern

```typescript
try {
  const response = await fetch('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(data)
  });

  if (!response.ok) {
    const error = await response.json();
    handleError(error);
    return;
  }

  const result = await response.json();
  handleSuccess(result);
} catch (err) {
  showError("Network error. Please check your connection.");
}

function handleError(error) {
  const { error_code, detail, error_type, request_id } = error;

  // User/frontend error
  if ([400, 422].includes(response.status)) {
    showUserMessage(detail); // Show detail directly to user
  }
  
  // Rate limit
  if (response.status === 429) {
    disableFormTemporarily(); // Disable form for 5+ minutes
    showWarning(detail);
  }
  
  // Server error
  if (response.status >= 500) {
    console.error(`Server error [${request_id}]:`, error);
    showError(`${detail} (ID: ${request_id})`);
  }
}
```

### 2. Error Type Handling

```typescript
// VALIDATION_ERROR: Input validation issues
if (error.error_type === 'validation_error') {
  highlightFormField(); // Show which field has issue
  showInlineError(detail);
}

// BUSINESS_LOGIC_ERROR: Valid input, but business rules violated
if (error.error_type === 'business_logic_error') {
  showCenteredWarning(detail);
  // Usually doesn't require field highlight
}

// RATE_LIMIT: Too many requests
if (error.error_type === 'rate_limit') {
  disableFormButton();
  showCountdownTimer();
  retryAfterDelay(60000); // Retry after 1 minute
}

// SERVER_ERROR: Backend issue
if (error.error_type === 'server_error') {
  logToSentry(error); // Send to error tracking
  showErrorWithSupport(detail, error.request_id);
}
```

### 3. Request ID for Support

Always include `request_id` in support/error tickets:

```typescript
// On error, show this to user
`An error occurred (ID: ${error.request_id}). Please provide this ID to support.`

// Save to logs/analytics
logEvent('api_error', {
  request_id: error.request_id,
  error_code: error.error_code,
  endpoint: '/api/auth/register',
  timestamp: error.timestamp
});
```

### 4. UX Best Practices

**DO:**
- Show the `detail` message directly to users
- Include request IDs in error dialogs
- Disable form submission on rate limit (429)
- Show which field is invalid for validation errors
- Log server errors (5xx) to your error tracking system

**DON'T:**
- Expose raw error objects to users
- Ignore rate limit errors
- Retry immediately on 500 errors
- Show technical details like stack traces
- Treat all 4xx errors the same way

---

## Common Error Scenarios

### Scenario: User tries to register twice with same email

```json
{
  "error_code": "EMAIL_ALREADY_REGISTERED",
  "detail": "This email is already registered. Please log in or use a different email.",
  "error_type": "business_logic_error"
}
```

**Frontend action:** Show the message and link to login page.

### Scenario: User enters invalid PIN

```json
{
  "error_code": "PIN_INVALID",
  "detail": "Invalid PIN. 4 attempts remaining.",
  "error_type": "validation_error"
}
```

**Frontend action:** Show error, let user try again. After 5 failed attempts, show "Please request new PIN".

### Scenario: User tries resend PIN 3 times in a day

```json
{
  "error_code": "DAILY_LIMIT_EXCEEDED",
  "detail": "You can resend the PIN maximum 2 times per day. Please try again tomorrow.",
  "error_type": "rate_limit"
}
```

**Frontend action:** Disable resend button, show message, retry tomorrow.

### Scenario: Email service temporarily down

```json
{
  "error_code": "EMAIL_SERVICE_FAILED",
  "detail": "Failed to send verification email. Please try again or contact support.",
  "error_type": "server_error",
  "request_id": "req-123-abc"
}
```

**Frontend action:** Show error with request ID, log to monitoring, suggest retry in 5 minutes.

---

## Migration from Old Format

If your frontend was using the old error format (just a string detail), update to use `error_code` and `error_type`:

### Old (don't use)
```json
{ "detail": "Email already registered" }
```

### New (use this)
```json
{
  "error_code": "EMAIL_ALREADY_REGISTERED",
  "detail": "This email is already registered. Please log in or use a different email.",
  "error_type": "business_logic_error",
  "request_id": "req-123"
}
```

Check `error.error_code` in frontend instead of parsing `error.detail` string.
