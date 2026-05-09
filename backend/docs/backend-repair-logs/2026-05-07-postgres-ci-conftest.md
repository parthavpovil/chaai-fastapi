# §12.2 — Postgres in CI; Remove SQLite conftest Monkey-Patches

## Problem

`conftest.py` ran tests against SQLite with two monkey-patches:

```python
SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "TEXT"
SQLiteTypeCompiler.visit_VECTOR = lambda self, type_, **kw: "TEXT"
```

Tests could pass while Postgres-specific behaviour (JSONB operators, `tsvector`
FTS, pgvector cosine similarity, `GENERATED ALWAYS AS`) silently failed in
production.  The `asyncio.gather` session bug that reached `main` (commits
`a8a2d96` / `1d80ee7`) is an example of a failure class that SQLite cannot
detect.

## Fix

### `.github/workflows/test.yml` — added service containers

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    env:
      POSTGRES_USER: chatsaas_user
      POSTGRES_PASSWORD: testpassword
      POSTGRES_DB: chatsaas_test
    options: --health-cmd pg_isready ...

  redis:
    image: redis:7-alpine
    options: --health-cmd "redis-cli ping" ...
```

The test step now passes:
```
DATABASE_URL: postgresql+asyncpg://chatsaas_user:testpassword@localhost:5432/chatsaas_test
REDIS_URL: redis://localhost:6379/0
```

`pgvector/pgvector:pg16` includes the `vector` extension pre-installed, matching
the production database image.

### `conftest.py` rewritten

- Removed the SQLite monkey-patches and `sqlite+aiosqlite:///:memory:` engine.
- `db_engine` fixture is session-scoped: creates all tables once, drops them after.
- `db_session` fixture is function-scoped: yields a session, rolls back after each test.
- Kept `mock_db_session` (AsyncMock) for pure unit tests that don't need a real DB.

## Files Changed

- `.github/workflows/test.yml` — added `postgres` and `redis` service containers
- `backend/conftest.py` — removed SQLite shortcut; `db_session` now uses real Postgres
