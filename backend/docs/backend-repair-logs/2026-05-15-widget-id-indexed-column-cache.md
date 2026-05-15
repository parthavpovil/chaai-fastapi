# widget_id lookup: indexed column + L1/L2 cache + lifespan pre-warm

Follow-up to the worker-timeout cascade repair
(`2026-05-15-worker-timeout-and-lifespan-cascade.md`). That repair stopped
the SIGKILLs. This one eliminates the slow path that caused the original
`/api/webchat/send` 504s.

## Problem

`get_webchat_channel_by_widget_id` is called by four hot paths:

1. `POST /api/webchat/send` — every widget message
2. `GET /api/webchat/messages` — widget polling (fires every few seconds)
3. `POST /api/webchat/upload` — widget file upload
4. Customer WebSocket auth (`/ws/webchat/...`)

The function was scanning every active webchat channel and Fernet-decrypting
every encrypted field of every channel's `config` JSONB to find the one whose
decrypted `widget_id` matched. Cold-cache request timing logs from production:

| Send | `channel lookup done` | total |
|---|---|---|
| 1 (cold) | +46.72 s | 47.87 s |
| 2 (cold, different worker) | +10.58 s | 12.59 s |
| 3 (warm) | +0.08 s | 2.20 s |

Cold requests routinely exceeded nginx's 60s upstream timeout → 504s.
`pg_stat_user_tables` confirmed: 285k seq_scans on `channels` accumulated
in a few days. The earlier commit `a24634a` added an in-process LRU which
helped on cache hits but couldn't help the first request on each gunicorn
worker.

**Severity:** Critical for UX. Widget chat is the primary product surface;
every cold path was a 5–47 s wait or a 504.

## Root cause

`channels.widget_id` did not exist as a column. The value was buried inside
the encrypted `config` JSONB blob. Postgres can't index it there (the values
are non-deterministic Fernet ciphertexts), so every lookup was forced to do
a sequential scan of the whole `channels` table and decrypt every row's
config to find a match.

## Fix

Three layered changes. The schema fix is the real win; the cache layer and
pre-warm reduce the cold-worker tax to zero. From the
`get_webchat_channel_by_widget_id` stack now:

| Layer | Hit cost | Lives in |
|---|---|---|
| L1: per-worker in-process dict (60s TTL) | ~ns | `app/services/widget_cache.py` |
| L2: Redis `widget:{widget_id}` key (300s TTL) | ~1 ms | `app/services/widget_cache.py` |
| L3: indexed `SELECT WHERE widget_id = $1` | ~1 ms | `app/routers/webchat.py` + migration 033 |
| L4: legacy scan+decrypt (defensive only) | 10–50 s | `app/routers/webchat.py` |

L4 only fires for deploy-race orphans (a channel that has widget_id in
encrypted config but NULL in the column). It logs a loud WARNING per fire
so an operator can backfill the orphan, and is removed in the cleanup PR
once L4 firings hit zero for a week.

### Schema (migration 033)

`backend/alembic/versions/033_add_channels_widget_id_column.py`:

1. `ADD COLUMN widget_id VARCHAR(36)` (nullable). Metadata-only DDL on
   PG ≥11 — no table rewrite, near-instant.
2. Backfill: SELECT every webchat channel's config, decrypt
   `config["widget_id"]` via `app.services.encryption.decrypt_credential`,
   UPDATE the new column. ~25 rows finish sub-second. Rows that fail to
   decrypt fall back to the raw value and log a WARNING with the channel id.
3. `CREATE UNIQUE INDEX ix_channels_widget_id ON channels (widget_id) WHERE
   widget_id IS NOT NULL` — partial index excludes non-webchat channels
   (telegram/whatsapp/instagram have widget_id NULL).

Downgrade is clean: drop index, drop column.

### L1 + L2 cache (`backend/app/services/widget_cache.py`, new)

Mirrors the proven pattern in `app/services/workspace_cache.py` (short-lived
Redis client, fail-silent on errors). Owns both layers behind a single
unified API:

- `get_cached_channel_id(widget_id)` — L1 → L2 lookup, populates L1 on L2
  hit.
- `set_cached_channel_id(widget_id, channel_id)` — writes both L1 and L2.
- `invalidate_widget_cache(widget_id)` — clears both. Called from channel
  update/delete after commit.
- `bulk_set_cached_channel_ids(mapping)` — Redis-pipeline pre-warm,
  fills L1 first then ships the L2 set in one round-trip.

Why L2 in addition to L1: a freshly-spawned gunicorn worker has an empty
L1 dict. With L2 (shared via Redis), the very first request on a cold
worker hits a key populated by a sibling worker or by the lifespan
pre-warm, so the cold-worker tax is bounded to ~1 ms instead of ~1 ms +
indexed-SELECT cost.

### Lifespan pre-warm (`backend/main.py`)

A new `_prewarm_widget_cache()` runs once per worker after `init_db()`:

```python
SELECT id, widget_id
FROM channels
WHERE type='webchat' AND is_active=True AND widget_id IS NOT NULL
```

…then `bulk_set_cached_channel_ids(mapping)`. Bounded by
`asyncio.wait_for(..., timeout=3.0)`. On timeout or any exception it logs
WARNING and lets workers warm lazily — startup is never blocked.

### Reads swapped to the column

- `webchat.py:get_webchat_channel_by_widget_id` — now goes L1→L2→L3→L4
  instead of always doing the scan+decrypt.
- `webchat.py:get_webchat_config` — reads `channel.widget_id` from the
  column with a fallback to decrypted config for transition rows.
- `channels.py:_build_webchat_platform_info` — same. Still decrypts the
  OTHER WidgetConfig fields (business_name, colors, etc.) from `config`.
- `webhook_handlers.py:get_channel_by_webhook_path` — was using
  `Channel.config["widget_id"].astext == identifier`, which never matched
  for webchat because the JSONB value is ciphertext. Migration 033 fixes
  that latent bug as a side effect; the query is now
  `Channel.widget_id == identifier`.

### Writes write both, for one deploy cycle

- `channels.py:create_channel` — writes widget_id to BOTH the new column
  AND the encrypted `config` blob for one deploy cycle of backward compat.
  Lets old-code workers (still running mid-deploy) keep reading from
  config. The cleanup PR drops the config copy a week later.
- `channels.py:update_channel` — preserves the existing encrypted
  widget_id (was already doing this). Calls `invalidate_widget_cache(...)`
  after commit so other workers see deactivations within their L1 TTL.
- `channels.py:delete_channel` — captures widget_id before delete, calls
  `invalidate_widget_cache(...)` after commit.

### Removed (no longer useful)

The step-timing diagnostic logs added in `f8669b9`:
- `[webchat/send] enter @ +0.00s`-style ticks in `webchat.py`
- `[preprocess_message] ...`-style ticks in `message_processor.py`

They served their purpose (pinpointed the bottleneck to
`get_webchat_channel_by_widget_id`).

## Why this approach

- **Indexed column is the only fix that fundamentally scales.** All other
  approaches (cache, pre-warm, smarter scan) are workarounds. Once
  widget_id is its own column, the lookup is `WHERE col = $1` against a
  B-tree index — O(log N) up to millions of widgets with no further
  work. L2 and pre-warm are layered on for cold-worker latency, not
  scalability.
- **Migration backfill imports app code.** Alembic supports this; the
  encryption service is initialized at import time and `ENCRYPTION_KEY`
  is in the migration container's env. The alternative (two-step deploy
  with double-writes then a separate backfill script) is safer for big
  tables, but ~25 rows in a single migration is fine and atomic.
- **Backward-compat double-write for one cycle.** Keeping widget_id in
  encrypted `config` for a week eliminates the deploy-race window
  entirely. L4 fallback is the safety net for any orphan that slips
  through.
- **L4 fallback is intentionally noisy.** It should fire zero times in
  steady state. If it ever fires, the WARNING tells an operator
  immediately so they can backfill.

## Verification

Local:
- All 9 changed files: `py_compile` clean.
- `docker build`: exit 0, image rebuilt.
- Inside the container: `Channel.widget_id` resolves to
  `VARCHAR(36) NULLABLE UNIQUE INDEX`. `widget_cache` module exports all
  4 helpers. Migration 033 imports with correct revision chain
  (`down_revision = "032_add_password_reset_pin"`).
- Lifespan smoke test (stubbed DB): worker reaches "PAST YIELD" within
  ~2 s, event loop ticks every 500 ms, clean shutdown. Pre-warm timeout
  on missing DB logs WARNING and does NOT block startup.

Production (to run after `git push origin main` triggers the deploy):

1. Migration ran:
   ```sql
   \d+ channels
   ```
   Shows `widget_id varchar(36)` + `ix_channels_widget_id` partial unique.
   ```sql
   SELECT count(*) FROM channels
   WHERE type='webchat' AND widget_id IS NULL;
   ```
   Should be 0.

2. Cold-cache cost gone:
   Same 3-shot curl test from a24634a's validation:
   ```
   POST /api/webchat/send (widget_id=cfac3d71-..., random session_token)
   ```
   Every shot's `total_time` should be ~2 s (everything below the channel
   lookup) instead of 5–47 s. With `_prewarm_widget_cache` in lifespan,
   even the very first request on every worker hits the warm cache.

3. No regressions on the 7 read sites: agent dashboard channel listing,
   public `/api/webchat/config/{slug}`, customer WS auth, webhook routing,
   channel create / update / delete.

4. `pg_stat_user_tables` sanity:
   ```sql
   SELECT relname, seq_scan, idx_scan FROM pg_stat_user_tables
   WHERE relname = 'channels';
   ```
   `seq_scan` should grow slowly, `idx_scan` should grow with widget
   traffic.

5. L2 layer is doing work:
   ```bash
   docker exec chatsaas-redis redis-cli KEYS 'widget:*'
   ```
   Should show ~25 keys after the first pre-warm.

6. L4 monitoring:
   ```bash
   docker logs chatsaas-backend | grep "L4 fallback fired"
   ```
   Should be empty in steady state. Any fire is a flag to backfill the
   logged channel id.

## Frontend Impact

None. The widget continues to call the same endpoints. Response payload
shape is unchanged. The only user-visible difference is that responses
arrive in <2 s instead of 5–47 s.

## Files Changed

New:
- `backend/alembic/versions/033_add_channels_widget_id_column.py`
- `backend/app/services/widget_cache.py`

Modified:
- `backend/app/models/channel.py`
- `backend/app/routers/channels.py`
- `backend/app/routers/webchat.py`
- `backend/app/services/webhook_handlers.py`
- `backend/app/services/message_processor.py` (removed diagnostic ticks only)
- `backend/main.py` (lifespan pre-warm)
- `backend/tests/test_webchat_endpoints.py` (mock updated to match new path)

`backend/gunicorn.conf.py` is intentionally untouched.

## Scalability

| Widget count | L1 hit | L2 hit | L3 hit (cold) | Pre-warm at startup |
|---|---|---|---|---|
| 50 (current target) | <1 µs | ~1 ms | <1 ms | ~5 ms |
| 1,000 | <1 µs | ~1 ms | <1 ms | ~30 ms |
| 10,000 | <1 µs | ~1 ms | ~1 ms | ~200 ms |
| 100,000 | <1 µs | ~1 ms | ~1–2 ms | ~2 s |
| 1,000,000 | <1 µs | ~1 ms | ~2 ms | ~20 s — drop pre-warm |

Memory: L1 is ~80 bytes/entry × workers (negligible up to 100k widgets);
L2 is ~80 bytes/key in Redis (80 MB for 1M widgets); the partial unique
index is ~32 bytes/row (32 MB for 1M webchat channels).

## Related commits

- `e16434a` — this change
- `a24634a` — earlier in-process cache (now subsumed by L1 inside
  widget_cache.py)
- `ad7b6b4` — DB-session-per-message fix (separate root cause; ended the
  WORKER TIMEOUT cascade)
- `107e219` — redis_pubsub busy-loop fix (separate root cause; ended the
  lifespan hang)

## Follow-ups

- **Cleanup PR (after 1 week)**: drop the widget_id copy from encrypted
  `config`, drop the L4 fallback once L4 WARNING count is 0 for the week.
- **Drop encryption on widget_id entirely**. It's a public identifier
  embedded in widget JS, not a secret — encrypting it was unnecessary
  legacy.
- **Consider promoting other lookup keys** in `channels.config` to their
  own columns (telegram `bot_token`, whatsapp `phone_number_id`, etc.).
  The same scan+decrypt pattern exists for webhook routing in
  `webhook_handlers.py:_matches_channel_identifier`; that's the next
  candidate.
- **Cosmetic**: the two arq worker containers
  (`chatsaas-message-worker-paid`, `-free`) still inherit the
  Dockerfile's `curl :8000/health` HEALTHCHECK and show `unhealthy` in
  `docker ps` even though they're processing cron jobs correctly. A
  `healthcheck: disable: true` override in `docker-compose.prod.yml`
  fixes the cosmetic issue (deploy gate ignores it anyway).
