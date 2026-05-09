# Backend Architecture Review — chaai / ChatSaaS Backend

**Reviewer:** Senior Architect (read-only audit)
**Scope:** `/backend` — FastAPI 0.111 + SQLAlchemy 2.0 async + Postgres/pgvector + Redis/arq + Razorpay/Resend + WebSockets, deployed via Docker Compose / Gunicorn / Nginx.
**Date:** 2026-05-07
**Branch:** `main` @ `a8a2d96`
**Mode:** Brutally honest. No participation trophies.

---

## 0. Executive Summary

This codebase is a competent v1 SaaS backend that works, has good async hygiene in most places, and clearly belongs to an engineer who knows FastAPI. It is **not** ready for "real production traffic" in the sense the prompt asked about — there are concrete bugs that will fire under load, several architectural choices that will be expensive to undo later, and a handful of security/availability flaws that should be fixed in the next 1–2 sprints.

**The five things that should keep you up at night:**

1. **`preload_app = True` in [gunicorn.conf.py:44](../gunicorn.conf.py#L44) combined with the async SQLAlchemy engine in [app/database.py:14-21](../app/database.py#L14-L21).** The engine (and any connection it lazily opened) is created in the master process before fork. asyncpg/asyncio pools are not fork-safe. This is a latent corruption bug, not a style issue.
2. **Nginx `proxy_*_timeout 60s` ([nginx.conf:38-40](../nginx.conf#L38-L40)) is shorter than Gunicorn's `timeout=120` ([gunicorn.conf.py:19](../gunicorn.conf.py#L19)) and the codebase explicitly says RAG calls take 60–90s.** Long RAG/LLM responses get 504'd by Nginx silently. The user retries, the worker keeps processing the orphan, the queue inflates.
3. **No login rate limiting at all** on `/api/auth/login`, `/api/auth/agent-login`, or `/api/auth/register`. Combined with HS256 JWT and a 7-day expiry default, any leaked credential or weak password is a disaster.
4. **Inbound webhooks for Telegram/WhatsApp/Instagram are not idempotent and silently swallow handler errors while still returning 200.** Carriers retry. Errors are invisible. Both bugs at once is the worst combination — duplicate processing AND lost-error invisibility.
5. **Conversation list queries have no supporting index.** `list_conversations()` filters by `(workspace_id, status)` and orders by `updated_at` against a table with no index on any of those columns. Today it's fast because the table is small. At 100k conversations it will be the dominant query and you will not notice until it's already painful.

**What's actually good** is below in §2 — short list, on purpose.

**Bottom line scores** (justified in §13):

| Dimension | Score |
|---|---|
| Scalability | **4 / 10** |
| Maintainability | **5 / 10** |
| Security | **4 / 10** |
| Production readiness | **4 / 10** |

This is a "works on staging, will get you to first 100 paying tenants" backend. It is not "I can hand this to a 5-person team and walk away" backend.

---

## 1. Folder & Code Geography (the lay of the land)

```
backend/
├── main.py                       236 LOC — app composition, lifespan, health
├── app/
│   ├── config.py                 227 LOC — pydantic-settings + tier limits
│   ├── database.py                78 LOC — async engine + get_db
│   ├── routers/                   26 files (~3.5k LOC)
│   ├── services/                  46 files (~15k LOC)  ← the real codebase
│   ├── models/                    29 files
│   ├── schemas/                    4 files            ← suspiciously thin
│   ├── middleware/                 3 files
│   ├── tasks/                      5 files            ← arq workers
│   └── utils/
├── alembic/versions/              26 migrations, linear
├── gunicorn.conf.py
├── docker-compose.prod.yml
├── nginx.conf
└── chatsaas-backend.service       (legacy systemd path)
```

**Smells visible from orbit:**

- `services/` is **15k LOC across 46 files** and `schemas/` is **4 files**. The split is wrong. Most of `services/` should be split into `services/{domain}/{...}` packages, and request/response shapes belong in `schemas/` not in ad-hoc `Body(...)` dicts (see §6).
- Five files are over the "you should split this" threshold:
  - `services/rag_engine.py` — ~1,142 LOC, doing retrieval + ranking + generation + caching.
  - `services/websocket_manager.py` — ~830 LOC, mixing agent-WS and customer-WS lifecycles.
  - `services/ai_provider.py` — ~778 LOC, four providers in one factory.
  - `services/webhook_handlers.py` — ~647 LOC, three channels in sequence.
  - `services/conversation_manager.py` — ~659 LOC, every conversation operation.
- `routers/conversations.py` is **45.8 KB / ~13 endpoints in one file**. That router will be the merge-conflict factory once a second engineer joins.

This isn't a death sentence — it's a debt. But it's the first thing that will hurt when you grow the team.

---

## 2. What's Actually Good (and *why*)

I'm not going to be nice for the sake of it, but credit where it's due:

- **Lifespan and shutdown are done correctly** ([main.py:28-78](../main.py#L28-L78)). Background tasks start in `startup`, are cancelled in `shutdown`, and Redis pub/sub is awaited cleanly. Most teams get this wrong.
- **Cross-worker WebSocket broadcast via Redis pub/sub** ([main.py:55-62](../main.py#L55-L62)) — correct architectural choice. Lots of teams ship in-memory dicts and discover horizontal scaling is broken on day one.
- **`arq` job dedup via `_job_id=msg:<message_id>`** ([app/tasks/message_tasks.py:54-80](../app/tasks/message_tasks.py#L54-L80)) — exactly the pattern you want for an at-least-once message pipeline.
- **Per-workspace concurrency semaphore via Redis Lua script** ([app/tasks/message_tasks.py:30-35](../app/tasks/message_tasks.py#L30-L35)) — atomic acquire/release, tier-aware. Good.
- **Reconciliation sweeper** ([app/tasks/reconciliation.py](../app/tasks/reconciliation.py)) re-enqueues orphaned messages — i.e., you've thought about partial failure.
- **JWT blocklist on logout** in Redis until token `exp` — proper logout, not just "throw the token away on the client."
- **Hybrid retrieval (HNSW + GIN tsvector)** with RRF + MMR re-ranking — modern RAG, not "we shoved everything into pgvector and called it a day."
- **`expire_on_commit=False, autoflush=False`** ([app/database.py:24-30](../app/database.py#L24-L30)) — correct for async; this trips up most teams.
- **Hardened systemd unit** ([chatsaas-backend.service](../chatsaas-backend.service)) — `ProtectSystem=strict`, `NoNewPrivileges=true`, `LimitNOFILE=65536`. Above-average for a startup.
- **`SplitCORSMiddleware`** ([main.py:100-122](../main.py#L100-L122)) — correctly distinguishes embeddable widget routes (need `*`) from dashboard routes (strict allowlist). This is a real engineering decision, not a copy-paste.

OK, that's the nice part. Moving on.

---

## 3. Database & Data Layer

### 3.1 — Missing composite indexes on the hottest list query

**Problem.** `routers/conversations.py` filters every list call by `workspace_id` + `status` and orders by `updated_at`. There is no index on `conversations.(workspace_id, status)` and none on `conversations.(workspace_id, updated_at)`. Postgres does not auto-create indexes on FK *child* columns, only on PK side. See [app/models/conversation.py](../app/models/conversation.py).

**Impact.** Every conversation list = full table scan + sort. With 100k conversations and 1k workspaces, p95 will collapse, the planner will do a `Sort` node that spills to disk on big workspaces, and pagination will become "load 50k rows, throw away 49,950."

**Severity:** **CRITICAL** — silent until it isn't.

**Fix.**
```python
__table_args__ = (
    Index("ix_conversations_workspace_updated", "workspace_id", "updated_at"),
    Index("ix_conversations_workspace_status", "workspace_id", "status"),
)
```
Add an Alembic migration. For status — since cardinality is ~4 — a partial index per status (e.g. `WHERE status = 'escalated'`) is even better for the dashboard.

### 3.2 — `Message.external_message_id` dedup constraint is *commented* but never created

**Problem.** [app/models/message.py:54-58](../app/models/message.py#L54-L58) has a comment: *"Unique constraint for external message deduplication ... will be created as a partial unique index in migration."* No such migration exists. The code comment is a lie.

**Impact.** If Telegram or WhatsApp redelivers a webhook (they do — at-least-once is their contract), and the application-level dedup misses it, you get duplicate messages, duplicate billing, duplicate AI replies. This has already been observed enough that you wrote a `reconciliation.py`.

**Severity:** **HIGH**.

**Fix.** Migration:
```sql
CREATE UNIQUE INDEX CONCURRENTLY ix_messages_external_id_unique
ON messages (external_message_id) WHERE external_message_id IS NOT NULL;
```

### 3.3 — Workspace deletion cascades through 17 relationships, no soft delete anywhere

**Problem.** [app/models/workspace.py:14-69](../app/models/workspace.py#L14-L69) declares `cascade="all, delete-orphan"` across 17 child relationships (channels, conversations, documents, ai_agents, contacts, broadcasts, …). There is no `deleted_at` column anywhere in the schema. A bug, a misclick, or a malicious admin = irrecoverable data loss.

**Impact.** GDPR/legal-hold story is bad. Customer support story is bad ("can you restore X?" — "no, only from yesterday's backup, and we'll lose 12h"). Billing reconciliation is bad (Razorpay invoice references a workspace that no longer exists).

**Severity:** **HIGH** for compliance posture, **MEDIUM** day-to-day.

**Fix.** Introduce `deleted_at TIMESTAMPTZ NULL` on `workspaces`, `users`, `documents`, `conversations`, `messages`, `agents`. Replace cascading deletes with cascading soft-deletes. Run a hard-delete reaper once per week for rows older than 30 days.

**Better design.** Per-row tenancy gets cleaner if you also add a `WorkspaceState` enum (`active | suspended | deleted | exporting`) — billing suspension and deletion are different states with different UX consequences.

### 3.4 — Sequential `COUNT(*)` storms in `TierManager`

**Problem.** [app/services/tier_manager.py:65-104](../app/services/tier_manager.py#L65-L104) issues 4–5 sequential `COUNT(*)` queries (channels, agents, documents, usage) for the *same* workspace on quota checks.

**Impact.** Every "create channel/agent/document" path adds 4 round-trips before the actual work. At a 5ms LAN RTT each, that's 20ms of pure quota-check overhead per write. Worse: counts on `documents`/`messages` get progressively slower without supporting indexes (§3.1).

**Severity:** **MEDIUM**.

**Fix.** One query:
```python
select(
    select(func.count(Channel.id)).where(Channel.workspace_id == ws_id).scalar_subquery().label("channels"),
    select(func.count(Agent.id)).where(Agent.workspace_id == ws_id).scalar_subquery().label("agents"),
    ...
)
```
Or precompute counters in `usage_counters` and increment atomically (see §3.5 for why you need atomic updates anyway).

### 3.5 — Tier quota checks are check-then-create (TOCTOU)

**Problem.** [routers/channels.py](../app/routers/channels.py) (and equivalents for agents/documents) does:
```python
await tier_manager.check_channel_limit(workspace_id)
# ... window where another request can also pass ...
db.add(Channel(...))
await db.commit()
```
**Impact.** Two concurrent "create" requests both pass the limit check, both insert. A free-tier (limit=1) workspace ends up with 2 channels.

**Severity:** **MEDIUM** — exploitable by anyone scripting their own dashboard.

**Fix.** Either:
- Use `SELECT ... FOR UPDATE` on a `usage_counters` row inside an explicit transaction, or
- Use a Postgres CHECK with a counter row updated via `UPDATE ... SET n = n+1 WHERE n < limit RETURNING n`. If no row is returned, reject.

### 3.6 — Migration 023 has a `TRUNCATE TABLE documents CASCADE`

**Problem.** [alembic/versions/023_add_hnsw_and_fts_to_chunks.py:29](../alembic/versions/023_add_hnsw_and_fts_to_chunks.py) executes `TRUNCATE TABLE documents CASCADE`. Comment: *"existing data not needed; new docs re-uploaded."*

**Impact.** If this migration is ever re-applied to a prod DB (recovery scenario, branch rebase, alembic stamp confusion, accidental `downgrade` then `upgrade`), all documents and chunks are deleted with no warning.

**Severity:** **HIGH** for ops safety.

**Fix.** Either:
- Replace with a one-time data-migration script that's *not* in the alembic chain, or
- Guard with `if not _data_already_migrated(connection): return` so it's idempotent.

### 3.7 — No `selectinload` on conversation/message fetch in RAG

**Problem.** [services/rag_engine.py:506-521](../app/services/rag_engine.py#L506-L521) issues two queries: one for `Conversation`, then one for `Message`. Should be one query with `.options(selectinload(Conversation.messages))`.

**Impact.** Doubled latency on every RAG call. Recent commits already had to serialize these because they were running in `asyncio.gather` against the same session and exploding (see §4.1) — a single eager-loaded query removes the concurrency entirely.

**Severity:** **MEDIUM**.

### 3.8 — No explicit `pool_size` set on the async engine

**Problem.** [app/database.py:14-21](../app/database.py#L14-L21) sets `pool_pre_ping=True, pool_recycle=3600` but no `pool_size` or `max_overflow`. SQLAlchemy defaults to `pool_size=5, max_overflow=10` per worker process.

**Impact.** With Gunicorn `workers ≤ 4` plus the message-worker container, that's potentially `5 × (5+10) = 75` Postgres connections fighting for whatever Postgres `max_connections` is. On a default Postgres install (`max_connections=100`) you have ~25 connections of headroom for migrations, monitoring, psql sessions. Easy to exhaust during a deploy.

**Severity:** **MEDIUM** — depends on tuning.

**Fix.** Set explicitly, sized to your `max_connections`. With pgbouncer in transaction-pooling mode, set engine `poolclass=NullPool` and let pgbouncer pool. Without pgbouncer, `pool_size=10, max_overflow=5, pool_timeout=10`.

### 3.9 — pgvector HNSW config is fine, BM25 maintenance isn't

**Problem.** Migration 023 creates the HNSW index well. But `content_tsv` is populated by a manual bulk `UPDATE` from `embedding_service`, not by a Postgres trigger. If a chunk is inserted from anywhere else (or if the bulk update is interrupted), `content_tsv` is empty and BM25 silently returns nothing.

**Impact.** Quiet retrieval-quality regression. Hard to detect until users complain that the bot got dumber.

**Severity:** **MEDIUM**.

**Fix.** Either a `BEFORE INSERT/UPDATE` trigger that recomputes `tsvector(content)`, or a `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` column. The generated column is the modern Postgres way.

---

## 4. Concurrency & Async

### 4.1 — `preload_app = True` with the async SQLAlchemy engine

**Problem.** [gunicorn.conf.py:44](../gunicorn.conf.py#L44) sets `preload_app = True`, which imports the FastAPI app *in the master process before fork*. Importing `app.database` instantiates `engine = create_async_engine(...)`. asyncpg / SQLAlchemy async pools are not fork-safe — file descriptors and the asyncio loop state get inherited by every worker.

**Impact.** Symptoms range from "weird hangs on first request after deploy" to "occasional `InvalidRequestError` to "two workers race on the same TCP connection." Hard to diagnose; looks like flakiness.

**Severity:** **CRITICAL** — bug, not preference.

**Fix.** Either:
- `preload_app = False`, or
- Keep `preload_app = True` but null out the engine after fork:
  ```python
  def post_fork(server, worker):
      from app.database import engine
      engine.sync_engine.pool.dispose()
  ```
  And ensure the engine is lazily reconstructed in each worker.

### 4.2 — `threading.Lock` held inside async `dispatch()`

**Problem.** [app/middleware/monitoring_middleware.py:35, 49, 85, 122, 155, 218, 223](../app/middleware/monitoring_middleware.py#L35) — `self.lock = threading.Lock()` is acquired on every request inside the async middleware path.

**Impact.** Two issues:
1. `threading.Lock` blocks the event loop. Every request takes a microsecond hit; under contention (which `with self.lock` will produce) the loop stalls.
2. Inside a single Gunicorn `UvicornWorker`, all "concurrency" is asyncio coroutines sharing one OS thread — so a `threading.Lock` is *trying to protect against threads that don't exist*. It's a misunderstanding of the runtime.

**Severity:** **MEDIUM** — perf and correctness ambiguity.

**Fix.** Replace with simple in-coroutine reads/writes (asyncio is single-threaded; you don't need a lock at all for `defaultdict[int]` increments inside one worker). For cross-worker metrics, push to Redis or a real metrics library (see §9.1).

### 4.3 — `asyncio.gather` on a shared session was banned by recent commits, but no static guard

**Problem.** Commits `a8a2d96` and `1d80ee7` fixed `asyncio.gather(self.db.execute(...), self.db.execute(...))` patterns — SQLAlchemy `AsyncSession` forbids concurrent operations on the same session. Nothing prevents this from being reintroduced.

**Impact.** Next person who writes "let me parallelize these" reintroduces the bug; it shows up only under load (when sessions are pool-borrowed cold).

**Severity:** **MEDIUM** — institutional, not local.

**Fix.** Add a lint rule (`ruff` or `semgrep`) that bans `asyncio.gather(*..., db.execute(...))`. Or wrap session in a class that asserts a re-entrancy counter. At minimum, write a `CONTRIBUTING.md` rule and a unit test that fails if any service uses `gather` on `self.db`.

### 4.4 — Background tasks via `asyncio.create_task(trigger_event(..., db))`

**Problem.** Some routers fire-and-forget event triggers ([routers/contacts.py:219](../app/routers/contacts.py#L219)). The current `trigger_event` opens its own session (good — fixed in `fbd8203`). But the *pattern* of `asyncio.create_task(...)` with no error capture means if any future variant does pass `db`, you get the same class of bug, and there's no retry.

**Impact.** Lost outbound webhook events on errors. No visibility.

**Severity:** **MEDIUM**.

**Fix.** Push outbound events to arq (you already run it), not `asyncio.create_task`. That way: retries, dead-letter, observability all come for free.

---

## 5. Security & AuthZ

### 5.1 — No rate limiting on `/api/auth/login`, `/api/auth/agent-login`, `/api/auth/register`

**Problem.** [routers/auth.py](../app/routers/auth.py) has zero rate limiting. The webchat router applies `check_webchat_rate_limit` but auth does not.

**Impact.** Credential stuffing trivially exploits this. A botnet can probe 10 RPS per IP, 1000 IPs → 10k attempts/sec against bcrypt with no slowdown.

**Severity:** **CRITICAL**.

**Fix.** Either:
- Add a Redis token-bucket limiter (10 attempts / 5 minutes / email + IP), or
- Use `fastapi-limiter` and key on `request.client.host`.

Combine with: temporary lockout after N failures, captcha on the front-end after M, password breach check via HaveIBeenPwned API on register.

### 5.2 — JWT default expiry of 7 days, HS256, no refresh-token rotation

**Problem.** [app/config.py:42](../app/config.py#L42) sets `JWT_EXPIRE_MINUTES` default = 10080 (7 days). `auth_service` uses HS256. The "refresh" endpoint takes the existing access token and issues a new one with extended `exp`.

**Impact.**
- 7 days is too long for an access token. A device-stealer or token-leak yields a 7-day window.
- HS256 + symmetric secret means anyone who reads your env can forge tokens.
- "Refresh" without a separate refresh token means leaking a token = unbounded refresh.

**Severity:** **HIGH**.

**Fix.** Standard split:
- Access token: 15 minutes, RS256, signed with rotating private key.
- Refresh token: 30 days, opaque random string, stored hashed in `refresh_tokens` table with `user_id`, `device_fingerprint`, `expires_at`, `revoked_at`. Refresh rotates (issue new refresh, mark old revoked).
- Logout revokes the refresh token row.
- The Redis access-token blocklist becomes optional belt-and-suspenders.

### 5.3 — WebSocket auth via query-string token

**Problem.** [routers/websocket.py:25-75](../app/routers/websocket.py#L25-L75) accepts the JWT in `?token=...`.

**Impact.** Tokens land in:
- Nginx access logs (yes, even with TLS).
- Browser history.
- Any HTTP referer header if the WS endpoint is loaded inside an iframe.
- Crash dumps and APM tools.

**Severity:** **HIGH**.

**Fix.** Use a short-lived (60-second) one-time WS-ticket endpoint: client POSTs `/api/auth/ws-ticket` with normal Bearer auth → gets a single-use ticket → opens `wss://.../ws/{workspace_id}?ticket=<...>`. Server validates ticket from Redis (key once, expire 60s), then upgrades.

Bonus: works across CORS without needing custom WS subprotocols.

### 5.4 — Telegram / WhatsApp / Instagram inbound webhooks not signature-verified

**Problem.** Resend (Svix HMAC) and Razorpay (HMAC) signatures are verified. Telegram secret-token header, WhatsApp `X-Hub-Signature-256`, Instagram signature — all rely only on the URL path / channel-config token in the body. See [routers/webhooks.py:276+](../app/routers/webhooks.py#L276).

**Impact.** Anyone who knows your webhook URL (or guesses it) can POST forged messages — fake user messages, fake delivery receipts, fake billing-completed events. They will be processed end-to-end.

**Severity:** **HIGH** — and this is a "your bot replied to a forged user" story that lands in PRs and screenshots.

**Fix.** Verify each provider's signature:
- Telegram: compare `X-Telegram-Bot-Api-Secret-Token` header to a workspace-specific secret set when you `setWebhook`.
- WhatsApp: HMAC-SHA256 of the request body using `WHATSAPP_APP_SECRET`, compared with `X-Hub-Signature-256`.
- Instagram: same scheme as WhatsApp/Meta.
Wrap as a `verify_inbound_webhook(provider, request)` dependency.

### 5.5 — Webhook signature verifier swallows exceptions and returns False

**Problem.** [routers/webhooks.py:131](../app/routers/webhooks.py#L131):
```python
except Exception as e:
    logger.error("Resend signature verification error: %s", e)
    return False
```

**Impact.** A malformed timestamp, a missing key, a broken `cryptography` install — all become "invalid signature" with no operator alerting. You'll discover it weeks later when someone notices their billing emails aren't reflecting.

**Severity:** **MEDIUM**.

**Fix.** Catch only the specific exceptions you expect (`InvalidSignatureError`, `KeyError`). Let the rest 500 — at least you'll see them.

### 5.6 — Ad-hoc broad `except Exception` in HTTP handlers leaks stack messages

**Problem.** [routers/documents.py:118, 179, 219, 254, 297, 363](../app/routers/documents.py) all do:
```python
except Exception as e:
    raise HTTPException(status_code=500, detail=f"Failed to upload: {e}")
```

**Impact.** The `str(e)` of an `IntegrityError`, `botocore` error, or asyncpg error includes table names, column names, and sometimes data values. This is information-disclosure to any unauthenticated client.

`grep -rn "except Exception" app | wc -l` returned **243** occurrences. Even allowing for the legitimate ones, that's at least a hundred sites that need review.

**Severity:** **MEDIUM** (security-flavoured).

**Fix.** A single `@app.exception_handler(Exception)` that:
1. Logs the full exception with request-id (see §9.2).
2. Returns a generic `{"error": {"code": "internal_error", "request_id": "..."}}` to the client.

Then audit and remove the per-route `except Exception → HTTPException` blocks.

### 5.7 — Authorization is dependency-gated, but a few endpoints still trust path IDs

**Problem.** Most endpoints use `Depends(get_workspace_from_token)` and pass the workspace from the JWT — that's correct and matches the saved memory rule about router-level `require_permission()`. But for nested resources (e.g., `GET /api/conversations/{id}`), the `id` comes from the path and the lookup is `WHERE conversations.id = :id AND workspace_id = :ws_id`. That's *also* fine **as long as** every router does it. Spot checks of `agents.py` and `documents.py` need to confirm this everywhere — and that's exactly the kind of audit that should be done with a single `assert_owned(model, id, workspace_id)` helper, not 50 hand-written `WHERE` clauses.

**Severity:** **LOW–MEDIUM** — mostly OK today, fragile for new contributors.

**Fix.** Centralize:
```python
async def get_owned(model, id, workspace_id, db) -> model:
    obj = (await db.execute(
        select(model).where(model.id == id, model.workspace_id == workspace_id)
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(404)
    return obj
```
Then always: `conv = await get_owned(Conversation, id, ws.id, db)`.

### 5.8 — Secrets in `.env` baked into Docker container env

**Problem.** [docker-compose.prod.yml:49-105](../docker-compose.prod.yml) injects every secret from `.env` into container environment. They're then visible via `docker inspect`, leak into logs that print env, and end up in any process dump.

**Impact.** Any process that gets `docker.sock` (or any user with sudo on the host) reads all of `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, all the API keys, the Razorpay secret, and the Postgres password.

**Severity:** **MEDIUM** — given the deployment is a single VPS with a bare host running Docker, the blast radius is "anyone with VPS root" which is presumably already trusted. But this won't survive a compliance review.

**Fix.** Docker secrets / SOPS / a managed secret store (AWS SM, Vault) by the time you have multi-tenant compliance requirements (HIPAA, SOC2).

---

## 6. API Design Consistency

### 6.1 — No global exception handler; error envelopes vary by route

**Problem.** Different endpoints return different shapes:
- FastAPI default: `{"detail": "..."}`
- Permissions: `{"detail": {"code": "...", "permission": "...", "message": "..."}}`
- Webhooks: `{"status": "ok"}`
- Some routers: bare dicts.

**Impact.** Frontend has to special-case error parsing per endpoint. Logging/alerting can't filter by error code. Mobile/SDK clients get inconsistent contracts.

**Severity:** **MEDIUM**.

**Fix.** One shape:
```json
{ "data": {...} } or { "error": { "code": "string", "message": "human", "details": {...} } }
```
and one global `@app.exception_handler(Exception)` to enforce it.

### 6.2 — DELETE returns 200+body, POST/create returns 200 not 201

**Problem.** [routers/documents.py](../app/routers/documents.py): `DELETE /{id}` returns `{"success": true}` with status 200. Auth register and most creates return 200, not 201.

**Impact.** Caches and CDNs handle 200 vs 204 differently. Idempotency proxies treat 201 differently. SDK code generators get confused.

**Severity:** **LOW** — but you'll regret it at v2 of any client SDK.

**Fix.** `204 No Content` for DELETE without body, `201 Created` with `Location` header for POST creates.

### 6.3 — `request.credentials.get("bot_token")` instead of Pydantic

**Problem.** [routers/channels.py:185](../app/routers/channels.py#L185) does `request.credentials.get("bot_token")` — `credentials` is a generic dict on the request body. There's no schema validation, no required-field enforcement, no field-length cap.

**Impact.** Inconsistent validation; the next dev shipping a new credential type doesn't know they were supposed to add a Pydantic model.

**Severity:** **LOW**.

**Fix.** Discriminated union by channel type:
```python
class TelegramCredentials(BaseModel):
    bot_token: str = Field(min_length=10, max_length=100)
class WhatsAppCredentials(BaseModel):
    phone_number_id: str
    access_token: str
class CreateChannelRequest(BaseModel):
    type: Literal["telegram","whatsapp","instagram"]
    credentials: Annotated[Union[TelegramCredentials, WhatsAppCredentials, ...], Field(discriminator="type")]
```

### 6.4 — Pagination via `limit`+`offset` only

**Problem.** Used consistently — that's good — but `OFFSET` paginations are O(N) on Postgres. At 100k conversations, page 200 (`OFFSET 10000`) is slow.

**Impact.** Dashboard pagination becomes painful for power users.

**Severity:** **LOW**.

**Fix.** Cursor-based pagination on `(updated_at, id)` for any user-visible list.

---

## 7. Webhook Idempotency & Inbound Pipeline

### 7.1 — Inbound channel webhooks are *not* idempotent and run synchronously

**Problem.** The webhooks for Telegram/WhatsApp/Instagram in [routers/webhooks.py](../app/routers/webhooks.py) call `_run_message_pipeline()` directly inside the request, not via arq. Webchat *does* enqueue. The asymmetry is suspicious.

**Impact.**
- Carriers retry. No dedup at the edge → duplicate messages, duplicate AI replies, duplicate billing.
- Synchronous call inside the request means the carrier's webhook timeout (Telegram 60s, Meta 5–10s) controls your pipeline budget. RAG can take 60–90s. So you respond too late, the carrier retries, you process *again*, this time without dedup.

**Severity:** **CRITICAL**.

**Fix.**
1. Compute a stable idempotency key per provider:
   - Telegram: `update_id`.
   - WhatsApp: `entry[].changes[].value.messages[].id`.
   - Instagram: `entry[].messaging[].message.mid`.
2. Insert a `processed_webhooks(provider, idempotency_key)` row with `ON CONFLICT DO NOTHING`. If 0 rows inserted → already processed, return 200 silently.
3. Otherwise enqueue an arq job and return 200 *immediately*.
4. Make the actual processing job use the same `_job_id=msg:<id>` dedup pattern you already have for webchat.

### 7.2 — Webhooks return 200 even when the handler raised

**Problem.** [routers/webhooks.py:354-355, 387-388](../app/routers/webhooks.py#L354-L355) catch and log internal errors but return 200 OK to the carrier. The carrier therefore won't retry.

**Impact.** Lost messages. The reconciliation sweeper helps for the AI-reply case, but a flow-engine error on inbound never gets retried.

**Severity:** **HIGH**.

**Fix.** Two-step pattern:
- *Inbound HTTP handler*: only does signature verify + idempotency-key insert + enqueue. If any of those fail → 500 (let the carrier retry).
- *arq job*: does the actual flow engine work, with arq retries.

### 7.3 — Razorpay event handler is not idempotent

**Problem.** [routers/webhooks.py:230-271](../app/routers/webhooks.py#L230-L271). Signature is verified, but a re-delivered `subscription.activated` will run the tier-update logic again.

**Impact.** Mostly benign (idempotent state assignment), but `subscription.charged` will create duplicate `Payment` rows if you have one. And tier-change *audit logs* will show duplicate transitions.

**Severity:** **MEDIUM**.

**Fix.** Persist `processed_razorpay_event(event_id)` and short-circuit on conflict.

---

## 8. Background Jobs & Queue

### 8.1 — Single shared `max_jobs=20` bucket → noisy-neighbor

**Problem.** [app/tasks/message_tasks.py:383-390](../app/tasks/message_tasks.py#L383-L390) sets a single `max_jobs=20` for the worker. The per-workspace semaphore (`free=2, …, pro=10`) limits concurrent jobs *per workspace*, but if 20 free-tier workspaces each enqueue 2, the worker is saturated and pro tenants wait.

**Impact.** Free tier degrades pro tier latency. Exactly the inverted SaaS-tier story.

**Severity:** **HIGH** (revenue-shaped).

**Fix.** Either:
- Two arq queues — `messages_paid` and `messages_free` — each with its own worker container (and `max_jobs` sized for the SLA), or
- A weighted scheduler that consumes from a Redis sorted set keyed by tier.

### 8.2 — Semaphore release swallows exceptions → slot leak

**Problem.** [app/tasks/message_tasks.py:91-98](../app/tasks/message_tasks.py#L91-L98) `_release_semaphore()` catches all exceptions and only logs.

**Impact.** Under Redis blip → semaphore counter never decremented → over time, a tenant's effective concurrency drops to 0. Symptom: "messages stop being processed for X workspace, but no errors anywhere."

**Severity:** **MEDIUM**.

**Fix.**
- Use a TTL on the semaphore counter (already 300s — good, that's the safety net).
- Move release into a `finally` block tied to the job, plus a daily reaper that resets counters to 0 globally.
- Switch to a Redis `INCR`/`DECR` *with* TTL refresh on acquire, not on release.

### 8.3 — No DLQ, no failure visibility

**Problem.** arq fails are retried up to `max_tries=4`, then the job is silently dropped (the result is kept for 1h via `keep_result=3600` and that's it). There is no DLQ list, no alert.

**Impact.** Permanent message-processing failures are invisible until a customer complains.

**Severity:** **HIGH**.

**Fix.** In `process_message_job`'s outermost handler, catch terminal failure (`Retry` exhausted) and:
- `LPUSH` to `dlq:messages` with the job payload + traceback.
- Emit a Prometheus counter / Sentry event.

---

## 9. Caching, Rate Limiting, Observability

### 9.1 — Rate limiter stores timestamps in a Postgres `ARRAY` column

**Problem.** [app/services/rate_limiter.py:64-67](../app/services/rate_limiter.py#L64-L67) appends to an `ARRAY` column on every request and rewrites the row.

**Impact.** Every rate-limited request = one full row UPDATE on a hot row, potentially with array growth. At 10 RPS per IP per workspace, that's a write storm. Postgres is not a rate limiter.

**Severity:** **HIGH**.

**Fix.** Redis token bucket (`INCR` with `EXPIRE`) or sliding window log in a Redis sorted set (`ZADD` + `ZREMRANGEBYSCORE`). The library `aiolimiter` or `slowapi` with Redis backend works.

### 9.2 — No request-id, no structured logs, no tracing

**Problem.** No middleware injects a request-id. Logs are printf-style strings. No Sentry, no OpenTelemetry, no Jaeger. The "Prometheus" endpoint (`/metrics/prometheus`) is a hand-rolled SQL-query endpoint, not auto-instrumentation.

**Impact.**
- Correlating "user got 500" → "which line in which worker" is manual log-grepping across 4 workers.
- No latency histograms — you cannot answer "what's our p95 today?".
- No exception aggregation — bugs hide in 243 `except Exception` blocks.
- Prometheus endpoint hits the DB on every scrape; turning it on for real (every 10s) means a small but constant DB load just for metrics.

**Severity:** **HIGH** for production readiness.

**Fix.** A single sprint:
1. Add a `RequestIDMiddleware` that sets `X-Request-ID` and stores it in `contextvars`.
2. Switch logging to `structlog`, bind `request_id`, `workspace_id`, `user_id`.
3. Add `prometheus-fastapi-instrumentator` for HTTP latency histograms.
4. Add Sentry (`sentry_sdk.init(...)`); `before_send` to scrub PII.
5. Wire OpenTelemetry FastAPI + SQLAlchemy + httpx instrumentations to an OTLP collector.

### 9.3 — Health check hits DB and R2 every probe

**Problem.** [main.py:166-217](../main.py#L166-L217) — every health-check execs `SELECT 1` and a HEAD on R2.

**Impact.** With a load balancer probing every 10s × 4 workers = 0.4 DB pings/sec just for health, plus 0.4 R2 calls/sec. R2 charges per request. It's a few dollars a month, but it's also an availability dependency: R2 hiccup → health check fails → load balancer pulls the worker → cascading restart.

**Severity:** **MEDIUM**.

**Fix.** Two endpoints:
- `/healthz` — returns 200 if the process is alive (no I/O).
- `/readyz` — returns 200 if DB is reachable, *cached for 5 seconds*. Don't include R2 in readiness; degrade gracefully when storage is down.

### 9.4 — No caching of permissions / tier / workspace config

**Problem.** Every request re-fetches the workspace, tier permissions, agent permissions from Postgres.

**Impact.** Hot path includes 3-4 lookups that change once per hour at most. With a permissions JSONB scan on top.

**Severity:** **MEDIUM**.

**Fix.** Cache `(workspace_id) → workspace+tier+permissions` in Redis with 60s TTL. Invalidate on tier change / permission override.

---

## 10. Deployment & DevOps

### 10.1 — Nginx 60s vs Gunicorn 120s timeout mismatch

**Problem.** [nginx.conf:38-40](../nginx.conf#L38-L40) sets `proxy_connect_timeout 60s; proxy_send_timeout 60s; proxy_read_timeout 60s;`. [gunicorn.conf.py:18-19](../gunicorn.conf.py#L18-L19) explicitly says timeouts must support "60-90s" RAG calls and sets `timeout = 120`.

**Impact.** RAG/LLM calls between 60s and 120s get a 504 from Nginx while Gunicorn is still working. The user sees a failed request; the worker keeps generating; your billing logs the LLM call; nobody sees the answer. This is also a perfect retry-storm setup: client retries → Gunicorn now has 2 in-flight identical requests.

**Severity:** **HIGH**.

**Fix.** Set Nginx to ≥125s (always slightly above your app timeout):
```nginx
proxy_connect_timeout 10s;
proxy_send_timeout    125s;
proxy_read_timeout    125s;
```
And move LLM calls to streaming (SSE) so the user sees progress and Nginx sees bytes within the timeout window.

### 10.2 — `proxy_buffering off; proxy_request_buffering off;`

**Problem.** [nginx.conf:77-78](../nginx.conf#L77-L78) globally turns off proxy buffering on `/`.

**Impact.** Slow-loris attacks have a direct path to your workers. A client can dribble bytes for 60s and tie up a Gunicorn worker per slow connection.

**Severity:** **MEDIUM**.

**Fix.** Keep buffering off only for the SSE/streaming endpoints (use a separate `location /api/.../stream { proxy_buffering off; }`), keep it on (the default) for everything else.

### 10.3 — `client_max_body_size 10M` for document uploads

**Problem.** Documents (PDF) can exceed 10 MB easily. The user has a "documents" feature.

**Impact.** Larger PDFs return 413 Payload Too Large. You'll hear about this from a customer.

**Severity:** **LOW**.

**Fix.** Either bump to 50–100 MB, or — better — upload directly to R2 with a presigned URL, then notify the API of the new key.

### 10.4 — No resource limits in `docker-compose.prod.yml`

**Problem.** No `mem_limit`, no `cpus`, no `pids_limit` on any service.

**Impact.** A runaway request (RAG storing 10MB context, message worker eating memory in a loop) can OOM the whole VPS, which kills Postgres, Redis, *and* the backend.

**Severity:** **MEDIUM**.

**Fix.** Set realistic limits:
```yaml
backend:
  deploy:
    resources:
      limits: { memory: 1g, cpus: "1.0" }
postgres:
  deploy:
    resources:
      limits: { memory: 2g }
```
Plus restart policies tuned per service.

### 10.5 — `init-db.sql` exists but `entrypoint.sh` runs `alembic upgrade head`

**Problem.** Two sources of schema truth — a SQL bootstrap file and Alembic. If they drift, fresh installs and migrations diverge.

**Severity:** **LOW**.

**Fix.** Delete `init-db.sql`. Alembic is the only schema source.

### 10.6 — Documentation sprawl in repo root

**Problem.** Root and `backend/` contain ~15 `.md` files (CICD_SETUP_GUIDE, DATABASE_SETUP, GITHUB_SECRETS_REFERENCE, NGINX_SETUP_COMMANDS, PLATFORM_COSTS_AND_SETUP, PLATFORM_WEBHOOK_APIS, SECRETS_QUICK_REFERENCE, SSH_TROUBLESHOOTING, VPS_FRESH_SETUP, WEBHOOK_SECRETS_EXPLAINED, WEBHOOK_SECURITY_ARCHITECTURE, WHATSAPP_FEATURES, …).

**Impact.** New engineer can't find the canonical doc for any topic. Many will go stale and contradict each other within a year.

**Severity:** **LOW**.

**Fix.** One `docs/` tree with a single `README.md` index. Git history preserves the rest.

---

## 11. Architecture & Maintainability

### 11.1 — `services/` is a 46-file flat directory with five 600+ LOC files

Already covered in §1. This is the maintainability ceiling. Refactor target:

```
services/
├── rag/           # rag_engine, embedding_service, retrieval, generation
├── messaging/     # webhook_handlers, message_processor, conversation_manager
├── ai/            # ai_provider, providers/{openai,google,groq,anthropic}
├── ws/            # websocket_manager (split agent vs customer), redis_pubsub
├── billing/       # razorpay, tier_manager, subscription
├── auth/          # auth_service, token_blocklist, permissions
└── ...
```

### 11.2 — No dependency-injection container

**Problem.** Services instantiate dependencies inline (`RAGEngine(db)`, `TierManager(db)`). No DI container; testing requires patching modules.

**Impact.** Tests reach into module globals. Swapping providers (e.g., to use Anthropic instead of OpenAI for a tenant) requires code changes, not config.

**Severity:** **LOW–MEDIUM**.

**Fix.** FastAPI `Depends` already gives you most of DI; lean into it. Make `RAGEngine`, `AIProvider`, `BillingService` Depends-injected, and provide overrides in tests.

### 11.3 — Tier limits and 27-key permission JSONB hard-coded in `config.py`

**Problem.** [app/config.py:144-209](../app/config.py#L144-L209) and migration 024 hard-code tier limits and permission flags.

**Impact.** Changing pricing/limits requires a code deploy. Sales conversations get blocked on engineering.

**Severity:** **MEDIUM** — operational friction.

**Fix.** Move tier definitions to a `tier_definitions` table seeded by a one-time data migration; let admins edit via an admin UI. Cache in Redis (see §9.4).

### 11.4 — `webhook_handlers.py` glues three providers in one 647 LOC file

**Problem.** Telegram + WhatsApp + Instagram + (eventually) more channels in one module.

**Severity:** **LOW** — but fixing it scales linearly with channels added.

**Fix.** Plugin interface:
```python
class ChannelAdapter(Protocol):
    async def verify_signature(self, request: Request) -> bool: ...
    async def parse_inbound(self, payload: dict) -> NormalizedMessage: ...
    async def send_outbound(self, channel: Channel, msg: NormalizedMessage) -> None: ...

ADAPTERS: dict[ChannelType, ChannelAdapter] = {...}
```

---

## 12. Testing

### 12.1 — 38 test files vs 119 source files; no coverage gate

**Problem.** Test-to-source ratio ~1:3.1. No `pytest --cov` enforced in CI. No contract tests against Telegram/WhatsApp/Razorpay sandboxes. No load tests despite explicitly stating RAG calls take 60–90s.

**Impact.** Refactors are fear-driven. The bugs fixed in commits `a8a2d96` and `1d80ee7` (concurrent-session in `gather`) reached `main`, which means current tests don't exercise the concurrent paths.

**Severity:** **MEDIUM**.

**Fix.** This sprint:
- `pytest --cov=app --cov-fail-under=60` gate in CI; raise to 75 over 6 months.
- Contract tests: a fixture that POSTs realistic Telegram/WhatsApp/Razorpay payloads (record from sandbox) to your webhook routes.
- A `locust` or `k6` smoke test against staging in CI nightly: 50 RPS to webchat for 5 minutes; assert no 5xx, p95 < 5s.

### 12.2 — `conftest.py` monkey-patches JSONB/VECTOR for SQLite

**Problem.** Tests run on SQLite with patches; production is Postgres + pgvector.

**Impact.** ORM quirks (Postgres array operators, `tsvector` operations, RLS, etc.) are not exercised. Tests can pass while prod blows up.

**Severity:** **MEDIUM**.

**Fix.** Spin a Postgres in CI (`services: postgres` in GitHub Actions) — it's free and 30 seconds slower. The current SQLite shortcut is paying daily interest in false-confidence.

---

## 13. Top 10 Biggest Risks (ranked)

| # | Risk | Severity | Where |
|---|---|---|---|
| 1 | `preload_app=True` forks the async SQLAlchemy engine — latent corruption | **CRITICAL** | [gunicorn.conf.py:44](../gunicorn.conf.py#L44) + [database.py](../app/database.py) |
| 2 | Inbound channel webhooks are not idempotent and run synchronously | **CRITICAL** | [routers/webhooks.py:276+](../app/routers/webhooks.py) |
| 3 | No login rate limiting; HS256, 7-day JWT, no refresh rotation | **CRITICAL** | [routers/auth.py](../app/routers/auth.py), [config.py:42](../app/config.py#L42) |
| 4 | Conversation list queries lack supporting indexes | **CRITICAL** | [models/conversation.py](../app/models/conversation.py) |
| 5 | Nginx 60s timeout < Gunicorn 120s, with 60–90s RAG calls | **HIGH** | [nginx.conf:38-40](../nginx.conf#L38-L40) |
| 6 | Single shared `max_jobs=20` arq bucket — pro tier starves on free-tier load | **HIGH** | [tasks/message_tasks.py:383-390](../app/tasks/message_tasks.py#L383-L390) |
| 7 | No idempotency on Razorpay & no signature verification on Telegram/WhatsApp/Instagram | **HIGH** | [routers/webhooks.py](../app/routers/webhooks.py) |
| 8 | Rate limiter writes timestamps to a Postgres ARRAY on every request | **HIGH** | [services/rate_limiter.py](../app/services/rate_limiter.py) |
| 9 | No request-id, no structured logs, no Sentry, no OpenTelemetry, no DLQ | **HIGH** | [logging_config.py](../logging_config.py), everywhere |
| 10 | Workspace deletion cascades through 17 relations with no soft-delete | **HIGH** | [models/workspace.py](../app/models/workspace.py) |

---

## 14. Scores

### Scalability — **4 / 10**
The async stack and `arq` queue give the right *bones*, but: no DB pool tuning, fork-unsafe engine, ARRAY-based rate limiter, single arq bucket, missing indexes on the hottest list, sync inbound webhooks, no per-tenant queue isolation. You can probably handle ~50 concurrent paying tenants. You will not handle 500.

### Maintainability — **5 / 10**
Folder structure is mostly conventional, types are reasonable, the `services/` layer exists. But: 5 files >600 LOC, only 4 schema files, services not packaged by domain, 243 `except Exception` blocks, two sources of schema truth, 15 unindexed root markdown docs, no DI container, no consistent error envelope. New senior engineer gets productive in week 2; new junior in month 2.

### Security — **4 / 10**
Decent fundamentals (JWT blocklist, secret length constraints, signature verification on Resend/Razorpay) but multiple critical gaps: no login RL, missing inbound webhook signatures on three carriers, WS token in query string, JWT in env-baked secrets, broad exception leaks, no PII redaction in logs. A bored bug-bounty hunter would file four valid reports in an evening.

### Production Readiness — **4 / 10**
It's deployable and it runs. But: Nginx/Gunicorn timeout mismatch, fork-unsafe engine, no DLQ, no APM, no resource limits, no readiness/liveness split, Telegram retries cause duplicate messages, RAG long-tail collapses to 504s, no canary/feature-flagging, all secrets in env. Acceptable for closed beta. Not acceptable for paid GA.

---

## 15. Technical Debt Assessment

You have ~6–8 weeks of focused remediation between "running on luck" and "production-grade." Roughly:

- **Week 1–2 (hot fixes):** preload+pool fix, Nginx timeout, login RL, WS ticket auth, webhook idempotency keys, missing indexes, DELETE/POST status codes, fix `proxy_buffering`, scope `client_max_body_size`. *These are mechanical.*
- **Week 3–4 (correctness & ops):** soft-delete columns, atomic quota counters, Razorpay/inbound carrier signature verification, DLQ + Sentry + structlog + request-id, Redis-backed rate limiter, refresh-token rotation, tier-split arq queues. *Half of these need a migration.*
- **Week 5–6 (architecture):** split `services/` into domain packages, plugin-ize channel adapters, generated `tsvector` column, pgbouncer in front of Postgres, k8s-ready health/readiness probes, resource limits, CI Postgres + coverage gate + load smoke. *This is where tech debt actually shrinks.*

The debt is **not crippling** — there are no fundamental architectural mistakes (good async, good queue, good multi-tenancy keying). The debt is *operational and safety nets*.

---

## 16. Suggested Next Architecture Evolution (30 / 60 / 90)

### Day 30 — "Stop the bleeding"
1. Fix `preload_app` + connection pool sizing.
2. Bump Nginx proxy timeouts to ≥125s; segment `proxy_buffering` per route.
3. Login rate limit + refresh-token rotation.
4. WS auth via short-lived ticket.
5. Webhook idempotency keys + arq enqueue for all carriers.
6. Three migrations: `(workspace_id, updated_at)` index on conversations, partial unique on `external_message_id`, soft-delete columns.
7. Replace ARRAY-based rate limiter with Redis token bucket.
8. Global `@app.exception_handler` + audit + remove per-route `except Exception`.

### Day 60 — "Stand it up properly"
1. `structlog` + request-id middleware + Sentry + `prometheus-fastapi-instrumentator`.
2. OpenTelemetry FastAPI + SQLAlchemy + httpx → OTLP collector → Grafana Tempo / Honeycomb / Datadog.
3. Split arq into per-tier queues; add DLQ + alerts.
4. Move webhook signature verification into a `verify_inbound(provider)` Depends.
5. Plugin-ize channel adapters; split `services/` into domain packages.
6. Centralize `get_owned(model, id, ws_id)` and audit all path-id endpoints.
7. CI: Postgres service, `pytest --cov-fail-under=60`, weekly k6 smoke.

### Day 90 — "Make it scale"
1. Postgres connection pooler (pgbouncer in transaction-pooling) + tune engine `NullPool`.
2. Move workspace+permissions+tier hot path to Redis cache with explicit invalidation.
3. Stream LLM responses via SSE; remove the 60-90s synchronous tail.
4. Per-tenant arq queues with weighted consumption.
5. Replace single VPS Compose with a managed Postgres + Redis + container runtime (ECS / Fly / k8s) — readiness probes, HPA on queue depth.
6. Soft-delete reaper job; GDPR export endpoint.
7. Deprecate `init-db.sql` and the doc sprawl; consolidate into `docs/`.

---

## Appendix A — Verification commands the user can run

```bash
# Confirm broad-except count
grep -rn "except Exception" backend/app | wc -l

# Look for shared-session concurrency patterns reintroduced
grep -rn "asyncio.gather" backend/app

# Confirm pool_size never set
grep -rn "pool_size" backend/app

# Confirm preload setting
grep -n "preload_app" backend/gunicorn.conf.py

# Confirm no Sentry / OpenTelemetry imports
grep -rn "sentry_sdk\|opentelemetry\|structlog" backend

# Confirm missing index on conversations
grep -n "Index" backend/app/models/conversation.py

# Confirm webhook signature verification gaps
grep -n "verify\|signature\|hmac" backend/app/routers/webhooks.py
```

If the result of any of these surprises you, that's where to start.

---

*End of review. If you disagree with a severity, tell me which one and why — most of these are judgement calls that should be made with product context, not architecture context alone.*
