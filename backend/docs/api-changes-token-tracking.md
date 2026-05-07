# API Changes — Token Tracking & Cost Monitoring

**Branch:** main  
**Date:** 2026-05-06  
**Scope:** Super admin billing visibility + internal token tracking overhaul

---

## Summary

Two new super-admin-only endpoints added under `/api/admin/`.  
No breaking changes to any existing endpoints.  
Internal token accounting is now complete — every LLM call (RAG responses, query rewrites, summaries, escalation checks, agent calls) is captured and costed.

---

## New Endpoints

### 1. `GET /api/admin/token-usage`

Paginated, cross-workspace monthly cost summary. Sorted by `total_cost_usd` descending — highest-spend clients first.

**Auth:** Super admin only (`SUPER_ADMIN_EMAIL` env var)

**Query Parameters:**

| Parameter | Type   | Required | Default       | Description                              |
|-----------|--------|----------|---------------|------------------------------------------|
| `month`   | string | No       | Current month | Month in `YYYY-MM` format                |
| `tier`    | string | No       | —             | Filter by tier: `free` \| `starter` \| `growth` \| `pro` |
| `limit`   | int    | No       | `50`          | Max results (1–200)                      |
| `offset`  | int    | No       | `0`           | Pagination offset                        |

**Response: `200 OK`**

```json
[
  {
    "workspace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "workspace_name": "Acme Corp",
    "owner_email": "admin@acme.com",
    "tier": "pro",
    "month": "2026-05",
    "message_count": 4821,
    "tokens_used": 9642000,
    "total_input_tokens": 7230000,
    "total_output_tokens": 2412000,
    "total_cost_usd": 1.27
  },
  {
    "workspace_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "workspace_name": "TechStart Inc",
    "owner_email": "owner@techstart.io",
    "tier": "growth",
    "month": "2026-05",
    "message_count": 1203,
    "tokens_used": 2406000,
    "total_input_tokens": 1804500,
    "total_output_tokens": 601500,
    "total_cost_usd": 0.32
  }
]
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | UUID string | Workspace identifier |
| `workspace_name` | string | Workspace display name |
| `owner_email` | string | Email of workspace owner |
| `tier` | string | Current billing tier |
| `month` | string | Month key `YYYY-MM` |
| `message_count` | int | Total billed messages that month |
| `tokens_used` | int | Combined input+output tokens (from `usage_counters`) |
| `total_input_tokens` | int | Input tokens only (from `ai_agent_token_log`) |
| `total_output_tokens` | int | Output tokens only (from `ai_agent_token_log`) |
| `total_cost_usd` | float | Estimated USD cost at model pricing rates |

> **Cost rates used:**
> - `gemini-2.0-flash`: $0.000075/1K input · $0.0003/1K output
> - `gpt-4o-mini`: $0.00015/1K input · $0.0006/1K output
> - `llama-3.3-70b-versatile`: $0.00059/1K input · $0.00079/1K output
> - `claude-haiku-4-5`: $0.00025/1K input · $0.00125/1K output

---

### 2. `GET /api/admin/token-usage/{workspace_id}`

Detailed token and cost breakdown for a single workspace. Useful for investigating a client before changing their tier or invoicing them.

**Auth:** Super admin only

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `workspace_id` | UUID | Target workspace ID |

**Response: `200 OK`**

```json
{
  "workspace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "workspace_name": "Acme Corp",
  "owner_email": "admin@acme.com",
  "tier": "pro",
  "monthly_history": [
    {
      "month": "2026-05",
      "message_count": 4821,
      "tokens_used": 9642000,
      "total_cost_usd": 1.27
    },
    {
      "month": "2026-04",
      "message_count": 3910,
      "tokens_used": 7820000,
      "total_cost_usd": 1.03
    }
  ],
  "call_type_breakdown": [
    {
      "call_type": "rag_response",
      "input_tokens": 6800000,
      "output_tokens": 2200000,
      "cost_usd": 1.17,
      "call_count": 4821
    },
    {
      "call_type": "rag_rewrite",
      "input_tokens": 380000,
      "output_tokens": 120000,
      "cost_usd": 0.064,
      "call_count": 3210
    },
    {
      "call_type": "escalation_check",
      "input_tokens": 50000,
      "output_tokens": 92000,
      "cost_usd": 0.032,
      "call_count": 620
    },
    {
      "call_type": "rag_summary",
      "input_tokens": 12000,
      "output_tokens": 9600,
      "cost_usd": 0.004,
      "call_count": 48
    }
  ],
  "model_breakdown": [
    {
      "model": "gemini-2.0-flash",
      "input_tokens": 7230000,
      "output_tokens": 2412000,
      "cost_usd": 1.27,
      "call_count": 8699
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `workspace_id` | string | Workspace UUID |
| `workspace_name` | string | Workspace display name |
| `owner_email` | string | Owner email |
| `tier` | string | Current tier |
| `monthly_history` | array | Last 12 months. Each entry: `month`, `message_count`, `tokens_used`, `total_cost_usd` |
| `call_type_breakdown` | array | Cost grouped by call source (see table below) |
| `model_breakdown` | array | Cost grouped by model name |

**`call_type` values in `call_type_breakdown`:**

| Value | Source | Description |
|-------|--------|-------------|
| `rag_response` | RAG pipeline | Main LLM call that generates the customer-facing reply |
| `rag_rewrite` | RAG pipeline | Query rewriting for coreference resolution (only fires when conversation history exists) |
| `rag_summary` | RAG pipeline | Conversation summarization (fires every 20 messages, Growth+ tiers only) |
| `escalation_check` | Escalation classifier | LLM-based escalation detection per incoming message |
| `response_generation` | AI Agent | Agent's LLM response call |
| `tool_selection` | AI Agent | Agent's tool-selection call |

**Error Responses:**

| Code | Body | When |
|------|------|------|
| `404 Not Found` | `{"detail": "Workspace not found"}` | `workspace_id` does not exist |
| `403 Forbidden` | `{"detail": "Super admin access required"}` | Caller is not super admin |

---

## Existing Endpoints — No Breaking Changes

All existing endpoints return the same response shape as before. The internal changes (token tracking, cost accumulation) are transparent to API callers.

| Endpoint | Change |
|----------|--------|
| `GET /api/admin/overview` | No response change |
| `GET /api/workspace/overview` | No response change |
| `GET /api/ai-agents/{id}/analytics` | No response change |
| Webchat / Webhook message flows | No response change — internal token logging added but response payload identical |

---

## Internal Changes (Non-API)

These affect backend behaviour without changing any request/response contract:

- **`AI_PROVIDER`** switched to `google` (`gemini-2.0-flash`) in `.env`
- **`EMBEDDING_PROVIDER`** stays `openai` (`text-embedding-3-small`)
- All RAG LLM calls (rewrite, main response, summary) now write to `ai_agent_token_log`
- Escalation classifier LLM calls now write to `ai_agent_token_log`
- `usage_counters` now tracks `total_cost_usd` per workspace per month
- Duplicate `track_message_usage()` calls removed from webchat and webhook routers (was double-counting tokens)

---

## Migration Required

Run before deploying:

```bash
alembic upgrade head
```

Adds:
- `ai_agent_token_log.conversation_id` (nullable UUID FK)
- `ai_agent_token_log.call_source` (nullable varchar 30)
- `usage_counters.total_cost_usd` (numeric 12,8, default 0)
