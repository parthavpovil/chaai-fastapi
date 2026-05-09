# §12.1 — pytest-cov Coverage Gate + CI Test Job

## Problem

No coverage measurement, no coverage gate, no test job in CI.  38 test files
exist but nothing enforces they run on every PR or that coverage doesn't regress.
The `asyncio.gather` session bug (fixed in commits `a8a2d96` / `1d80ee7`) reached
`main` because no CI gate would have caught it.

## Fix

### `backend/requirements.txt`

Added `pytest-cov==5.0.0` to the Testing section.

### `backend/setup.cfg`

Created with `[tool:pytest]` and `[coverage:run]` / `[coverage:report]` sections:

```ini
[tool:pytest]
asyncio_mode = auto
testpaths = tests

[coverage:run]
source = app
omit = app/migrations/*, app/alembic/*, */tests/*, */__pycache__/*
```

### `.github/workflows/test.yml` (new)

A standalone `test` job that runs on every push and PR to `main`:

```
pytest --cov=app --cov-report=term-missing --cov-report=xml --cov-fail-under=20 -x tests/
```

Threshold set to **20%** as the initial passing bar (reflecting the current
SQLite-based test suite, which cannot exercise Postgres-specific paths).

**Target trajectory**: raise to 40% once a Postgres service container is added
to CI (§12.2); raise to 60% once integration tests cover the webhook and RAG
pipelines.

Coverage XML is uploaded as an artifact for 7 days so it can be consumed by
coverage tracking tools (Codecov, etc.) in a follow-on step.

### `deploy.yml` — stale `init-db.sql` references removed

Three references to `backend/init-db.sql` remained in the deploy workflow after
the file was deleted in §10.5 (ops-safety-fixes).  Removed from:
- "Transfer deployment files" scp command
- Deploy script `sudo cp /tmp/init-db.sql` + stale directory guard
- Deploy script `rm -f /tmp/init-db.sql` cleanup

## Files Changed

- `backend/requirements.txt` — added pytest-cov
- `backend/setup.cfg` (new) — pytest + coverage config
- `.github/workflows/test.yml` (new) — CI test job
- `.github/workflows/deploy.yml` — removed stale init-db.sql references
