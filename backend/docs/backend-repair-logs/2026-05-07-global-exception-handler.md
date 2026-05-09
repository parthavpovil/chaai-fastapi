# §6.1 — Global Exception Handler

## Problem

The app had no `@app.exception_handler` registrations. Unhandled exceptions
produced raw Starlette 500 responses whose body varied (sometimes a plain-text
traceback in debug mode, sometimes an opaque JSON blob). Two concrete risks:

1. **Information leak** — in any mode where Python traceback is rendered, file
   paths, internal variable names, and SQL queries can leak to the client.
2. **Inconsistent error shape** — `HTTPException` returns `{"detail": "..."}`,
   validation errors return `{"detail": [...]}`, and unhandled exceptions return
   something different again. Clients cannot rely on a stable error format.

**Severity:** Medium-high. Leak risk is low in production (Uvicorn suppresses
tracebacks by default) but inconsistent shapes break frontend error handling.

## Fix

Three `@app.exception_handler` decorators added to `main.py`:

### `StarletteHTTPException` handler
Replaces FastAPI's default. Normalizes every HTTP error to:
```json
{"detail": "<original detail>", "request_id": "<X-Request-ID or null>"}
```
Preserves `exc.headers` so `WWW-Authenticate: Bearer` on 401 responses
(set by `AuthenticationError` in `auth_middleware.py`) continues to be sent.

### `RequestValidationError` handler (422)
Replaces FastAPI's default validation error response. Same shape:
```json
{"detail": [<pydantic error objects>], "request_id": "<X-Request-ID or null>"}
```
Returns the full validation error list — these are not sensitive (they describe
the request schema, not internal state).

### `Exception` catch-all handler
Catches any exception not caught by the two above:
- Logs `ERROR` with `exc_info=True` (full traceback goes to log files / Sentry,
  never to the client)
- Returns HTTP 500 with only `{"detail": "Internal server error", "request_id": "..."}` — zero internal state exposed

The `request_id` field in every error body lets a user copy the ID from their
browser and hand it to an operator who can grep logs for that exact value.

## Frontend Impact

### What changes
All API error responses now include a `request_id` field alongside `detail`:
```json
{"detail": "...", "request_id": "550e8400-e29b-41d4-a716-446655440000"}
```
`request_id` is `null` when the error occurs outside a request context (rare).

### What frontend should do
- No breaking change — `detail` is still present with the same type as before
- Optionally surface `request_id` in error UIs ("Error ID: abc123 — contact support")
- Do not depend on `request_id` being non-null

### No frontend doc needed
Shape addition only; existing `detail`-reading code is unaffected.

## Files Changed

- `main.py` — imports + three exception handlers

## Testing Checklist

- [ ] 404 on an unknown route — verify `{"detail": "Not Found", "request_id": "..."}` shape
- [ ] POST with missing required field — verify 422 with error list + `request_id`
- [ ] Trigger an unhandled exception in a route — verify 500 returns `"Internal server error"` (no traceback), and full traceback appears in logs
- [ ] 401 from auth middleware — verify `WWW-Authenticate: Bearer` header is still present
