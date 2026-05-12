# Password Reset Frontend Implementation

**Date:** 2026-05-13  
**Feature:** PIN-based password reset with mandatory re-login

## User Flow

```
1. User clicks "Forgot Password"
   ↓
2. Enter email → POST /auth/forgot-password
   ↓
3. Success page → "Check your email for PIN"
   ↓
4. User receives email with 6-digit PIN (valid 10 minutes)
   ↓
5. Enter PIN → POST /auth/verify-password-reset
   ↓
6. PIN verified → Show password reset form
   ↓
7. Enter new password → POST /auth/reset-password
   ↓
8. Password reset successful → Redirect to login
   ↓
9. User logs in with new password → New access & refresh tokens issued
```

## API Response Shapes

### Step 1: Request PIN

**Request:**
```javascript
POST /auth/forgot-password
Content-Type: application/json

{
  "email": "user@example.com"
}
```

**Response (200):**
```json
{
  "message": "If an account exists, a PIN will be sent to the email address"
}
```

**Error Responses:**
- 429 `rate_limit_exceeded`: Too many attempts (max 10 per 5 minutes)
- 429 `daily_limit_exceeded`: Already sent 2 PINs today

**UI Handling:**
- Always show success message (no indication if email exists or not)
- Show rate limit error if returned
- Display "Check your email for PIN" message

### Step 2: Verify PIN

**Request:**
```javascript
POST /auth/verify-password-reset
Content-Type: application/json

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

**Error Responses:**
- 400 `invalid_pin`: PIN incorrect (shows remaining attempts)
- 400 `pin_expired`: PIN no longer valid (user must request new PIN)
- 400 `max_attempts_exceeded`: User exceeded 5 failed attempts, must request new PIN
- 404 `user_not_found`: No user with that email

**UI Handling:**
```javascript
if (response.status === 400) {
  if (response.data.code === 'invalid_pin') {
    // Show: "Incorrect PIN. You have X attempts remaining"
  } else if (response.data.code === 'pin_expired') {
    // Show: "PIN expired. Request a new PIN to continue."
    // Redirect to forgot-password form
  } else if (response.data.code === 'max_attempts_exceeded') {
    // Show: "Too many failed attempts. Request a new PIN."
    // Redirect to forgot-password form
  }
}
```

### Step 3: Reset Password

**Request:**
```javascript
POST /auth/reset-password
Content-Type: application/json

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

**Error Responses:**
- 400 `invalid_pin`: PIN does not match
- 400 `pin_expired`: PIN no longer valid
- 400 `validation_error`: Password too weak (field: "new_password")
- 404 `user_not_found`: User not found

**UI Handling:**
- After success: Clear all local session data (access token, refresh token, user info)
- Redirect to login page with message: "Password reset successful. Please log in with your new password."

## Frontend Components

### 1. Forgot Password Form

**File:** `src/pages/auth/ForgotPassword.tsx` (create new)

**Features:**
- Email input field
- Submit button → POST `/auth/forgot-password`
- Loading state during request
- Error handling with rate limit messages
- Success state shows: "Check your email for 6-digit PIN (valid 10 minutes)"
- "Back to Login" link

**Code Structure:**
```typescript
export const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await authApi.forgotPassword({ email });
      setSubmitted(true);
    } catch (err) {
      // Handle rate limits, generic errors
      if (err.code === 'rate_limit_exceeded') {
        setError('Too many attempts. Please try again later.');
      } else if (err.code === 'daily_limit_exceeded') {
        setError('PIN already sent today. Check your email or try tomorrow.');
      } else {
        setError('Request failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return <div>Check your email for PIN (valid 10 minutes)</div>;
  }

  return (
    <form onSubmit={handleSubmit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <button type="submit" disabled={loading}>{loading ? 'Sending...' : 'Send PIN'}</button>
      {error && <div className="error">{error}</div>}
    </form>
  );
};
```

### 2. Verify PIN Form

**File:** `src/pages/auth/VerifyPasswordResetPin.tsx` (create new)

**Features:**
- PIN input (6-digit code)
- POST `/auth/verify-password-reset`
- Attempt counter: "Attempt 1/5"
- Error messages for expired/max attempts (with link to request new PIN)
- Success → navigate to reset-password form (pass email)

**Code Structure:**
```typescript
export const VerifyPasswordResetPinPage: React.FC = () => {
  const { email } = useLocation().state; // From forgot-password
  const [pin, setPin] = useState('');
  const [attempts, setAttempts] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    try {
      const response = await authApi.verifyPasswordReset({ email, pin });
      // Store temp token, proceed to reset-password form
      navigate('/auth/reset-password', { state: { email, pin } });
    } catch (err) {
      if (err.code === 'invalid_pin') {
        setAttempts(prev => prev + 1);
        setError(`Incorrect PIN. Attempt ${attempts}/5`);
      } else if (err.code === 'pin_expired') {
        setError('PIN expired. Request a new PIN.');
      } else if (err.code === 'max_attempts_exceeded') {
        setError('Too many failed attempts. Request a new PIN.');
      }
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input value={pin} onChange={(e) => setPin(e.target.value)} maxLength="6" />
      <button type="submit">Verify PIN</button>
      {error && <div className="error">{error}</div>}
    </form>
  );
};
```

### 3. Reset Password Form

**File:** `src/pages/auth/ResetPassword.tsx` (create new)

**Features:**
- Password input field (with strength meter)
- Confirm password field
- POST `/auth/reset-password` with email, pin, new_password
- Validation: password must meet requirements
- Success → clear session, redirect to login with success message

**Code Structure:**
```typescript
export const ResetPasswordPage: React.FC = () => {
  const { email, pin } = useLocation().state;
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await authApi.resetPassword({ email, pin, new_password: password });
      
      // Clear session
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      
      // Redirect to login
      navigate('/auth/login', {
        state: { message: 'Password reset successful. Please log in with your new password.' }
      });
    } catch (err) {
      if (err.data?.field === 'new_password') {
        setError(`Invalid password: ${err.data.message}`);
      } else {
        setError('Failed to reset password. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input 
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="New password"
      />
      <input 
        type="password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        placeholder="Confirm password"
      />
      <button type="submit" disabled={loading}>{loading ? 'Resetting...' : 'Reset Password'}</button>
      {error && <div className="error">{error}</div>}
    </form>
  );
};
```

## Routing

Add to auth router:

```typescript
<Route path="/forgot-password" element={<ForgotPasswordPage />} />
<Route path="/verify-password-reset" element={<VerifyPasswordResetPinPage />} />
<Route path="/reset-password" element={<ResetPasswordPage />} />
```

## Login Page Changes

Add "Forgot Password?" link:

```typescript
<button type="button" onClick={() => navigate('/auth/forgot-password')}>
  Forgot Password?
</button>
```

## Session Cleanup

After password reset, clear all local session data:

```typescript
// authService.ts
export const clearSession = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user_info');
  sessionStorage.clear();
};
```

Call after receiving 200 response from `/auth/reset-password`.

## Error Codes

| Code | HTTP | Meaning | User Message |
|------|------|---------|--------------|
| `rate_limit_exceeded` | 429 | Too many requests | "Too many attempts. Please try again later." |
| `daily_limit_exceeded` | 429 | Already sent 2 PINs today | "PIN already sent today. Try again tomorrow." |
| `invalid_pin` | 400 | PIN hash doesn't match | "Incorrect PIN. You have X attempts remaining" |
| `pin_expired` | 400 | PIN past 10-min window | "PIN expired. Request a new one." |
| `max_attempts_exceeded` | 400 | Exceeded 5 failed attempts | "Too many attempts. Request a new PIN." |
| `validation_error` | 400 | Password too weak | Show field-specific message |
| `user_not_found` | 404 | No user with email | *(Generic success shown instead)* |

## Testing Checklist

- [ ] Forgot password form displays and submits email
- [ ] Success message shown: "Check your email for PIN (valid 10 minutes)"
- [ ] Rate limit error (429) displayed correctly
- [ ] Daily limit error shown if already sent today
- [ ] PIN form accepts 6-digit input
- [ ] Incorrect PIN shows error with attempt counter
- [ ] After 5 failed attempts, shown "Request a new PIN"
- [ ] Expired PIN shows error with link to request new
- [ ] Password form validates passwords match
- [ ] Password strength meter functional (optional but recommended)
- [ ] Success → session cleared, redirected to login
- [ ] Login succeeds with new password
- [ ] Old refresh token rejected after reset

## Security Notes

1. **No Email Enumeration:** Forgot password always returns success message
2. **Session Revocation:** After password reset, all old tokens invalidated
3. **PIN Expiry:** 10-minute window, displayed in email
4. **Attempt Limits:** Max 5 failed attempts per PIN request
5. **Daily Limits:** Max 2 PINs per calendar day
6. **Rate Limiting:** Max 10 requests per 5 minutes per email

## Dependencies

- React Router for navigation
- API client configured in `authApi`
- localStorage for session management
- No new npm packages required
