# §3.6 + §10.3 + §10.4 + §10.5 — Operations Safety Fixes

## §3.6 — Migration 023 TRUNCATE TABLE replaced with conditional DELETE

### Problem
`alembic/versions/023_add_hnsw_and_fts_to_chunks.py` contained:
```python
op.execute("TRUNCATE TABLE documents CASCADE")
```
If this migration were re-applied — during a disaster-recovery `downgrade` +
`upgrade`, a branch rebase, or an accidental `alembic stamp` — all documents
and chunks would be silently deleted with no confirmation or guard.

### Fix
Replaced with a conditional DELETE that only removes documents whose chunks
have no embeddings (i.e. were inserted before the HNSW column was added):
```sql
DELETE FROM documents
WHERE id NOT IN (
  SELECT DISTINCT document_id FROM document_chunks
  WHERE embedding IS NOT NULL
)
```
Safe to re-run: on a server where 023 has already run, the table is already
empty — the DELETE is a no-op.  On a recovery scenario with live data, only
incomplete rows are removed.

---

## §10.3 — `client_max_body_size` raised from 10 MB to 50 MB

### Problem
`nginx.conf` had `client_max_body_size 10M`.  PDFs commonly exceed 10 MB.
Any document upload larger than 10 MB silently returned `413 Payload Too Large`.

### Fix
`client_max_body_size 50M;`

For presigned-URL direct uploads (the long-term fix), this setting becomes
irrelevant, but 50 MB is the pragmatic production ceiling in the meantime.

---

## §10.4 — Resource limits added to docker-compose.prod.yml

### Problem
No `deploy.resources.limits` on any service.  A runaway RAG request or memory
leak in the message worker could OOM the entire VPS, taking down Postgres and
Redis with it.

### Fix
Added `deploy.resources.limits` to all five services:

| Service | memory | cpus |
|---|---|---|
| postgres | 2g | — |
| redis | 256m | 0.5 |
| backend | 1g | 1.0 |
| message-worker-paid | 1500m | 1.5 |
| message-worker-free | 512m | 0.5 |
| nginx | 128m | 0.25 |

**Note:** `deploy.resources` is honoured by Docker Compose V2 (`docker compose`
command) on plain `docker compose up`.  With Docker Compose V1 (`docker-compose`)
it is only enforced in Swarm mode.  Production deployments should use V2.

**Tuning guidance:** raise `message-worker-paid.memory` to `2g` if RAG
responses with large document context start hitting OOM kills.  Postgres can
usually run fine at 512 MB for <100k rows; raise to 4 GB if query sorts start
spilling to disk.

---

## §10.5 — `init-db.sql` removed; Alembic is the single schema source

### Problem
`init-db.sql` was mounted into `postgres:/docker-entrypoint-initdb.d/` in both
`docker-compose.yml` and `docker-compose.prod.yml`.  Its contents:

```sql
CREATE EXTENSION IF NOT EXISTS vector;        -- already done by database.py init_db()
GRANT ALL PRIVILEGES ON DATABASE ... TO ...;  -- redundant: POSTGRES_USER is already the owner
SET timezone = 'UTC';                         -- session-level, does not persist
```

Two sources of schema truth invite drift.  On a fresh install, the file ran
before Alembic; on an existing install it was ignored.  The mismatch was a
maintenance hazard.

### Fix
- Deleted `init-db.sql`.
- Removed the volume mount from `docker-compose.prod.yml` and `docker-compose.yml`.
- Schema is now exclusively managed by Alembic migrations.
- `database.py:init_db()` still runs `CREATE EXTENSION IF NOT EXISTS vector` on
  startup, covering fresh database bootstraps.

## Files Changed

- `alembic/versions/023_add_hnsw_and_fts_to_chunks.py` — TRUNCATE → conditional DELETE
- `nginx.conf` — client_max_body_size 10M → 50M
- `docker-compose.prod.yml` — deploy.resources.limits on all services; removed init-db.sql mount
- `docker-compose.yml` — removed init-db.sql mount
- `init-db.sql` — deleted
