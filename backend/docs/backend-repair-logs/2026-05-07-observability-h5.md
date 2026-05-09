# H5 — Observability: Request-ID, DLQ, Sentry, Prometheus

## Problem

The backend had zero correlated observability:
- No request correlation ID → impossible to link a user complaint to a specific
  log line across multiple log entries from the same request
- arq terminal failures (all 4 tries exhausted) were silently dropped — no
  alert, no replayable record, no operator notification
- No error tracking — unhandled exceptions only appeared in flat log files,
  requiring SSH + grep to find production errors
- No metrics endpoint — no way for Prometheus/Grafana to scrape request counts,
  latency histograms, or error rates

**Severity:** HIGH for production readiness. These gaps make debugging incidents
slow and error-prone.

## Fix Strategy

Tackle in dependency order:
1. **Request-ID middleware** (foundation — enables correlated log lines)
2. **DLQ for terminal arq failures** (safety net — no silent drops)
3. **Sentry SDK** (error tracking — alerting without SSH)
4. **Prometheus instrumentation** (metrics — dashboards without custom scraping)

## Exact Changes

### New: `app/utils/request_context.py`
Holds `_request_id_var: ContextVar[str]` and `get_request_id()`.
Kept in `utils/` (not `middleware/`) so `logging_config.py` can import it
without risking circular imports.

### New: `app/middleware/request_id_middleware.py`
`RequestIDMiddleware(BaseHTTPMiddleware)`:
- Reads `X-Request-ID` from incoming headers or generates a UUID4
- Sets `_request_id_var` for the lifetime of the request
- Echoes the ID back in the response `X-Request-ID` header
- Registered last in `main.py` so it wraps all other middleware

### Modified: `logging_config.py`
`JSONFormatter.format()` now lazy-imports `get_request_id()` and injects
`"request_id"` into every JSON log entry when one is available. The import is
inside the method to avoid import-time ordering issues (logging is configured
before the app is fully wired).

### Modified: `app/config.py`
Added:
- `SENTRY_DSN: str` — empty default disables Sentry
- `SENTRY_TRACES_SAMPLE_RATE: float = 0.1` — 10% performance traces by default

### Modified: `requirements.txt`
Added:
- `sentry-sdk[fastapi]>=2.0.0`
- `prometheus-fastapi-instrumentator>=0.6.0`

### Modified: `app/tasks/message_tasks.py`
Added `_MAX_TRIES = 4` constant (single source of truth — both WorkerSettings
reference it instead of hardcoding 4).

Added `_push_dlq(redis_client, message_id, conversation_id, workspace_id, error)`:
- Serialises failure record to JSON and `LPUSH`es it to `dlq:messages`
- Includes `message_id`, `conversation_id`, `workspace_id`, `error`, `failed_at`
- Swallows its own exceptions (DLQ write failure must not mask the original error)

`process_message_job` now has an `except Exception as exc:` block between the
inner `try` and the `finally: redis_client.aclose()`. The logic:
- If exception is `Retry` (concurrency backoff): skip DLQ, just re-raise
- If `job_try >= _MAX_TRIES` (terminal): push to DLQ, then re-raise
- Otherwise (transient, will retry): just re-raise

### Modified: `main.py`
`_init_sentry()` function (called at lifespan startup):
- No-ops when `SENTRY_DSN` is empty
- Initialises FastApiIntegration + StarletteIntegration + SqlalchemyIntegration
- `send_default_pii=False` globally
- `before_send` hook scrubs `authorization`, `cookie`, `x-api-key`,
  `x-process-secret` headers before any event is transmitted

Prometheus instrumentator mounted at module level (after `app = FastAPI(...)`):
```python
Instrumentator().instrument(app).expose(app, include_in_schema=False)
```
Exposes a Prometheus-scrapable `GET /metrics` endpoint. No conflict with the
existing `GET /api/metrics/*` router.

`RequestIDMiddleware` registered last (wraps all previous layers):
```python
app.add_middleware(RequestIDMiddleware)
```

## Frontend Impact

None. All changes are backend-internal.

## Deployment Notes

- `pip install -r requirements.txt` — installs `sentry-sdk` and
  `prometheus-fastapi-instrumentator`
- Set `SENTRY_DSN=https://...@sentry.io/...` env var to activate error tracking
- Set `SENTRY_TRACES_SAMPLE_RATE=0.05` in high-traffic production to reduce cost
- `/metrics` endpoint is open — restrict with Nginx `allow` directives if needed
- DLQ: monitor `LLEN dlq:messages` in Redis; replay by `RPOP`ing entries

## Testing Checklist

- [ ] Any request — verify `X-Request-ID` appears in response headers
- [ ] Check JSON log lines — verify `"request_id"` key matches response header
- [ ] Force a job to exhaust all retries — verify entry appears in `dlq:messages`
- [ ] Set `SENTRY_DSN` — verify Sentry receives a test event via `/health` 500 trigger
- [ ] Scrape `GET /metrics` — verify Prometheus histogram families are present
- [ ] Verify normal requests complete normally — no regression
