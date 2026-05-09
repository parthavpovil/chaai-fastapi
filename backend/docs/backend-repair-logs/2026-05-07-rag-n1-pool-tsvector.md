# §3.7 + §3.8 + §3.9 — RAG selectinload, DB Pool Size, BM25 tsvector Maintenance

---

## §3.7 — RAG `_get_conversation_data` N+1 style double query

### Problem

`rag_engine._get_conversation_data` issued two sequential queries:

```python
conv = await db.execute(select(Conversation).where(...))   # query 1
msgs = await db.execute(select(Message).where(...))         # query 2
```

Earlier commits had to serialise these (removing an `asyncio.gather`) because
SQLAlchemy's `AsyncSession` forbids concurrent operations. The residual risk:
any future developer who re-parallelises them would reintroduce the session
concurrency error.

### Fix

Use `selectinload(Conversation.messages)` so SQLAlchemy owns the two-query
batch internally:

```python
conv = (await db.execute(
    select(Conversation)
    .where(Conversation.id == conversation_id, ...)
    .options(selectinload(Conversation.messages))
)).scalar_one_or_none()

messages = sorted(conv.messages, key=lambda m: m.created_at)[-max_messages:]
```

Conversations are bounded (chatbot sessions, typically < 100 messages).
Sorting and slicing in Python for `max_messages = CONTEXT_MESSAGES * 2 = 20`
is negligible. The explicit second query and any temptation to gather it are
removed.

---

## §3.8 — No explicit `pool_size` on async engine

### Problem

`create_async_engine` in `app/database.py` set only `pool_pre_ping` and
`pool_recycle`. In production (DEBUG=False) SQLAlchemy defaulted to
`pool_size=5, max_overflow=10`.

With Gunicorn `workers ≤ 4` + the message-worker container:
`5 workers × (5 + 10) = 75 Postgres connections` fighting default
`max_connections=100`. A deploy or migration session eats the remaining 25.

### Fix

Added to `app/config.py`:
```
DB_POOL_SIZE: int = 10
DB_MAX_OVERFLOW: int = 5
DB_POOL_TIMEOUT: int = 10
```

`app/database.py` builds pool kwargs conditionally:
- DEBUG=True → `NullPool` (unchanged, safe for hot-reload)
- DEBUG=False → `pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW, pool_timeout=DB_POOL_TIMEOUT`

`NullPool` and `pool_size`/`max_overflow` are mutually exclusive in
SQLAlchemy so the old single-call with `poolclass=NullPool if DEBUG else None`
was silently using defaults in production.

**Tuning guidance:**
Size to: `(workers + 1) × pool_size + max_overflow ≤ max_connections - 10`
(leave 10 connections for migrations, psql, monitoring).
With pgbouncer in transaction-pooling mode, switch to `NullPool` for all
environments and let pgbouncer pool instead.

---

## §3.9 — `content_tsv` not populated when chunks inserted outside embedding_service

### Problem

`document_chunks.content_tsv` was a nullable TSVECTOR populated by a
manual `UPDATE` in `embedding_service._process_document_chunks`:

```python
await db.execute(text(
    "UPDATE document_chunks SET content_tsv = to_tsvector('english', content) "
    "WHERE document_id = :doc_id AND content_tsv IS NULL"
))
```

Any chunk inserted from another code path (future bulk import, test fixtures,
direct psql insert) would have `content_tsv IS NULL`. The BM25 query in
`rag_engine` guards with `AND dc.content_tsv IS NOT NULL`, so those chunks
silently return nothing from full-text search — a quiet retrieval regression
with no error.

### Fix

**Migration 030** (`030_content_tsv_generated_column.py`):
1. Drop `idx_chunks_content_tsv_gin` index.
2. Drop `content_tsv` column.
3. Re-add as `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`.
4. Recreate GIN index.

Postgres fills the column automatically on every INSERT and UPDATE, for all
paths, with no application code involved.

**ORM model** (`app/models/document_chunk.py`):
```python
content_tsv = Column(
    TSVECTOR,
    Computed("to_tsvector('english', content)", persisted=True)
)
```
`Computed(persisted=True)` tells SQLAlchemy to never include the column in
INSERT/UPDATE statements — attempting to write it would raise a Postgres error
(`ERROR: column "content_tsv" can only be updated to DEFAULT`).

**embedding_service** (`app/services/embedding_service.py`):
Removed the manual `UPDATE document_chunks SET content_tsv = ...` — it is
now a no-op from the application's perspective. The `text` import was also
removed as it is no longer used.

## Files Changed

- `app/services/rag_engine.py` — `_get_conversation_data`: selectinload + Python slice
- `app/config.py` — added `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`
- `app/database.py` — conditional pool kwargs; explicit production pool sizing
- `alembic/versions/030_content_tsv_generated_column.py` — new migration
- `app/models/document_chunk.py` — `Computed` column for `content_tsv`
- `app/services/embedding_service.py` — removed manual `content_tsv` bulk UPDATE

## Testing Checklist

- [ ] Upload a document → chunks have non-NULL content_tsv without any manual UPDATE call
- [ ] Insert a chunk via psql directly → content_tsv is populated automatically
- [ ] RAG hybrid search returns BM25 results for keyword queries
- [ ] `alembic upgrade head` on a populated DB completes without data loss
- [ ] `alembic downgrade -1` restores plain nullable content_tsv column
- [ ] In production, verify `SHOW max_connections` and confirm `pool_size + max_overflow` fits within headroom
