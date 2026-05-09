# §4.3 — AST Guard: asyncio.gather Must Not Share AsyncSession

## Problem

`asyncio.gather()` schedules multiple coroutines concurrently on the same
event-loop turn.  SQLAlchemy's `AsyncSession` wraps a single `asyncpg`
connection; asyncpg connections are not re-entrant.  If two coroutines that
share the same session both call `await session.execute(...)` and are
interleaved by `asyncio.gather`, the second will hit:

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called
```
or
```
asyncpg.exceptions._base.InterfaceError: cannot perform operation:
  another operation is in progress
```

The root cause was identified in `rag_engine.py` (fixed in §3.7/3.8).  To
prevent future regressions a static test is now in place.

## Fix

Added `backend/tests/test_no_gather_db_session.py`:

- Parametrised over every `*.py` file under `backend/app/`.
- For each file: parse the AST and walk all `Call` nodes.
- A violation is flagged when:
  1. The call is `asyncio.gather(...)`.
  2. At least one positional argument is itself a `Call` whose `.func` is an
     `Attribute` named `execute`, `scalar`, `scalars`, `scalar_one`,
     `scalar_one_or_none`, `get`, or `run_sync`, **and** whose receiver
     contains `"db"` or `"session"` in its unparsed name.
- The test fails with the file path, line number, and offending expression.

## Why AST, Not a Linter Rule

No off-the-shelf pylint/flake8 plugin covers this exact pattern.  An AST test
runs in `pytest`, participates in CI, and produces actionable output without
requiring an extra linter dependency.

## Files Changed

- `backend/tests/test_no_gather_db_session.py` (new)
