# AI Studio — Frontend Implementation Guide

> This document is written for frontend engineers building the **AI Studio** section of the dashboard.
> It covers every screen, every API call, every field, every edge case, and every UX behaviour needed.

---

## Table of Contents

1. [What is AI Studio?](#1-what-is-ai-studio)
2. [How the AI System Works (Mental Model)](#2-how-the-ai-system-works-mental-model)
3. [Tab 1 — AI Agents](#3-tab-1--ai-agents)
4. [Tab 2 — AI Config](#4-tab-2--ai-config)
5. [Tab 3 — AI Pipeline](#5-tab-3--ai-pipeline)
6. [Shared Concepts](#6-shared-concepts)
7. [Auth & Headers](#7-auth--headers)
8. [Error Handling](#8-error-handling)
9. [Tier Gating](#9-tier-gating)
10. [Current UI Bugs to Fix](#10-current-ui-bugs-to-fix)

---

## 1. What is AI Studio?

AI Studio is where the workspace owner configures how the platform's AI behaves. There are three things they control:

| Area | What it does |
|---|---|
| **AI Config** | Which AI provider (OpenAI / Google / Groq / Anthropic) to use and the API key |
| **AI Pipeline** | The "mode" — does the AI use uploaded documents (RAG) or a configured AI Agent to reply? |
| **AI Agents** | Create and manage AI bots — their personality, tools they can call, safety rules, and which channels they handle |

**In plain English:** AI Config = the engine. AI Pipeline = the strategy. AI Agents = the bots that use both.

---

## 2. How the AI System Works (Mental Model)

When a customer sends a message, the backend does this:

```
Incoming message
       │
       ▼
Is AI enabled for this workspace?
  No  → route to human agents
  Yes ↓
       ▼
What is ai_mode?
  "rag"      → use knowledge base documents to generate reply
  "ai_agent" → find the AI Agent assigned to this channel → run it
       ▼
Agent runs → may call HTTP tools → generates reply
If uncertain → escalates to human agents
```

This means:
- Without a configured **AI Config** (provider + API key), nothing works.
- The **AI Pipeline** `ai_mode` field is the master on/off switch between RAG and Agent mode.
- An **AI Agent** only handles messages on channels it is assigned to, and only when `ai_mode = "ai_agent"`.

---

## 3. Tab 1 — AI Agents

This is the most complex tab. It has multiple sub-screens.

### 3.1 Agents List Page

**What to show:** A list of all AI agents for this workspace.

**API:**
```
GET /api/ai-agents
Authorization: Bearer <token>
```

**Response shape:**
```json
[
  {
    "id": "uuid",
    "name": "Support Bot",
    "persona_tone": "friendly",
    "is_draft": true,
    "is_active": true,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:00Z",
    "tools": [...],
    "guardrails": [...]
  }
]
```

**UI requirements:**
- Show each agent as a card or table row.
- Show a **status badge**: `DRAFT` (yellow) if `is_draft=true`, `LIVE` (green) if `is_draft=false`.
- Show `is_active` as an enabled/disabled indicator.
- Clicking an agent opens the **Agent Detail View** (see 3.2).
- A **"+ New Agent"** button opens the Create Agent form (see 3.3).
- If list is empty, show a helpful empty state: *"No agents yet. Create your first AI agent to start automating conversations."*

**Tier gating:** If workspace tier is `free`, show a locked state with an upgrade prompt instead of the list. (Backend will return `402` on any agent API call for free tier.)

---

### 3.2 Agent Detail View

When the user clicks an agent from the list, show a detail page with **sub-tabs**:

```
[ Overview ] [ Tools ] [ Guardrails ] [ Channels ] [ Sandbox ] [ Analytics ]
```

---

### 3.3 Create / Edit Agent — Overview Tab

**Create API:**
```
POST /api/ai-agents
Authorization: Bearer <token>
Content-Type: application/json
```

**Edit API:**
```
PUT /api/ai-agents/{agent_id}
Authorization: Bearer <token>
Content-Type: application/json
```

**Full request body (all fields):**

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | Yes | — | Max 100 chars. Agent's internal name. |
| `system_prompt` | string | Yes | — | The core instructions for the AI. Large textarea. |
| `persona_name` | string | No | null | Display name the bot uses, e.g. "Aria". Max 50 chars. |
| `persona_tone` | string | No | `"friendly"` | Options: `friendly`, `professional`, `empathetic`, `concise` |
| `first_message` | string | No | null | Greeting message sent when conversation starts. |
| `escalation_trigger` | string | No | `"low_confidence"` | When to hand off: `low_confidence`, `explicit_request`, `always_after_n_turns` |
| `escalation_message` | string | No | `"Let me connect you with a team member."` | Message shown when escalating. |
| `confidence_threshold` | float | No | `0.7` | 0.0–1.0. Below this the agent escalates. Show a slider. |
| `max_turns` | integer | No | `10` | 1–50. Max back-and-forth before forced escalation. |
| `token_budget` | integer | No | `8000` | 1000–32000. Max tokens per conversation. Show as a slider. |

**Validation before submit:**
- `name` is required and not empty.
- `system_prompt` is required and not empty.
- `confidence_threshold` must be between 0 and 1.
- `max_turns` must be between 1 and 50.
- `token_budget` must be between 1000 and 32000.

**After create:** Navigate to the new agent's detail view. Show success toast: *"Agent created in draft mode."*

**Publish button:**
```
POST /api/ai-agents/{agent_id}/publish
```
- Only show "Publish" when `is_draft = true`.
- Backend validation: agent needs `system_prompt`, `escalation_message`, and at least 1 active tool.
- On `400` error, show the backend error message inline (it will explain what's missing).
- On success, update the badge from `DRAFT` to `LIVE`.

**Delete agent:**
```
DELETE /api/ai-agents/{agent_id}
```
- Always show a confirm modal: *"Delete this agent? This cannot be undone. Any channels using it will stop receiving AI replies."*
- On success (204), remove from list and navigate back to agents list.

---

### 3.4 Tools Sub-Tab

**What are tools?** Tools are HTTP APIs the AI can call during a conversation. Example: "Look up order status" calls your internal order API. The AI decides when to call them based on the user's message.

**List tools:**
```
GET /api/ai-agents/{agent_id}/tools
```
Tools are also included in the agent response, so you may already have them.

**Create tool:**
```
POST /api/ai-agents/{agent_id}/tools
```

**Tool create/edit fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | **snake_case only**, e.g. `get_order_status`. This is used internally by the LLM. Pattern: `^[a-z][a-z0-9_]*$` |
| `display_name` | string | Yes | Human-readable, e.g. "Get Order Status". Max 100 chars. |
| `description` | string | Yes | **Important:** The AI reads this to decide when to call the tool. Write it clearly. E.g. "Call this to look up a customer's order status by order ID." |
| `method` | string | Yes | Dropdown: `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `endpoint_url` | string | Yes | Full URL, e.g. `https://api.yourapp.com/orders/{order_id}` |
| `headers` | object | No | Key-value pairs, e.g. `{"Authorization": "Bearer token123"}` |
| `body_template` | object | No | JSON body template, only for POST/PUT/PATCH |
| `parameters` | array | No | Parameters the AI will fill in (see below) |
| `response_path` | string | No | Dot-notation path to extract from response, e.g. `order.status` |
| `requires_confirmation` | boolean | No | Default `false`. If `true`, ask user to confirm before calling. |
| `is_read_only` | boolean | No | Default `true`. Mark `false` if tool modifies data (e.g. cancels order). |

**Parameters array — each item:**
```json
{
  "name": "order_id",
  "type": "string",
  "required": true,
  "description": "The order ID to look up"
}
```
Type options: `string`, `integer`, `boolean`, `number`.

**Update tool:**
```
PUT /api/ai-agents/{agent_id}/tools/{tool_id}
```
Same fields as create, all optional.

**Delete tool:**
```
DELETE /api/ai-agents/{agent_id}/tools/{tool_id}
```
Confirm modal required.

**Test tool inline:**
```
POST /api/ai-agents/{agent_id}/tools/{tool_id}/test
Body: { "params": { "order_id": "12345" } }
```
Response:
```json
{
  "success": true,
  "data": { "status": "shipped" },
  "error": null,
  "latency_ms": 243,
  "status_code": 200
}
```
Show a "Test" button next to each tool. Opens a mini panel where you can fill param values and see the response. Show latency, status code, and the raw data. Green for success, red for failure with the error message.

---

### 3.5 Guardrails Sub-Tab

**What are guardrails?** Safety rules that prevent the AI from doing or saying certain things.

**List guardrails:**
```
GET /api/ai-agents/{agent_id}/guardrails
```

**Create guardrail:**
```
POST /api/ai-agents/{agent_id}/guardrails
Body:
{
  "rule_type": "forbidden_topic",
  "description": "Do not discuss competitor products"
}
```

| Field | Type | Options | Notes |
|---|---|---|---|
| `rule_type` | string | `forbidden_topic`, `forbidden_action`, `required_escalation` | Select from dropdown |
| `description` | string | — | Plain English description of the rule |

**Rule type explanations for UI tooltip:**
- `forbidden_topic` — The AI will not discuss this subject. E.g. "Do not discuss competitor pricing."
- `forbidden_action` — The AI will not perform this action. E.g. "Do not issue refunds directly."
- `required_escalation` — Always hand off to a human in this scenario. E.g. "Escalate all complaints about shipping damage."

**Delete guardrail:**
```
DELETE /api/ai-agents/{agent_id}/guardrails/{guardrail_id}
```
No confirm needed (guardrails are easy to re-add).

---

### 3.6 Channels Sub-Tab

**What this does:** Links the AI agent to one or more channels. When a message arrives on an assigned channel and `ai_mode = "ai_agent"`, this agent will handle it.

**Note:** Channel assignments are stored on the agent. To show which channels are currently assigned, use the `channel_assignments` from the agent response — but you'll also want to fetch all workspace channels so the user can pick which ones to add.

**Fetch all workspace channels:**
```
GET /api/channels
```

**Assign a channel:**
```
POST /api/ai-agents/{agent_id}/channels/{channel_id}
```
Returns 201 on success. Returns 404 if the channel doesn't belong to this workspace.

**Unassign a channel:**
```
DELETE /api/ai-agents/{agent_id}/channels/{channel_id}
```
Returns 204 on success.

**UI design:**
- Show all workspace channels as a list with a toggle/checkbox.
- Toggling ON calls the assign endpoint.
- Toggling OFF calls the unassign endpoint.
- Show channel type icons (WhatsApp, Telegram, WebChat, etc.) next to channel names.
- Show a warning if agent is draft: *"Assign channels now, but the agent won't go live until published."*

---

### 3.7 Sandbox Sub-Tab

**What it is:** A test chat interface where you can talk to the agent as if you were a customer. No real conversations are created, no quota is used.

**Send a message:**
```
POST /api/ai-agents/{agent_id}/sandbox/message
Body:
{
  "message": "What's the status of order #12345?",
  "conversation_id": "sandbox-<agent_id>"  // optional, include to maintain conversation history
}
```

**Response:**
```json
{
  "reply": "Your order #12345 is currently shipped and expected to arrive by Friday.",
  "escalated": false,
  "escalation_reason": null,
  "debug": {
    "tool_called": "get_order_status",
    "tool_params": { "order_id": "12345" },
    "tool_result": { "status": "shipped", "eta": "Friday" },
    "tool_success": true,
    "tool_latency_ms": 180,
    "model_used": "gpt-4o-mini",
    "input_tokens": 523,
    "output_tokens": 42,
    "cost_usd": 0.000085,
    "turn_count": 1,
    "escalated": false
  }
}
```

**UI design:**
- Chat bubble UI — user messages on right, agent replies on left.
- Below each agent reply, show a collapsible **"Debug Info"** panel showing:
  - Model used, input/output tokens, cost in USD
  - Tool called (if any), params sent, result received, latency
  - Whether escalation was triggered and why
- Show an `ESCALATED` badge if `escalated = true`.
- A **"Reset Conversation"** button that calls:
  ```
  DELETE /api/ai-agents/{agent_id}/sandbox/reset
  ```
  Clears the conversation history and starts fresh.

---

### 3.8 Analytics Sub-Tab

**API:**
```
GET /api/ai-agents/{agent_id}/analytics
```

**Response:**
```json
{
  "agent_id": "uuid",
  "total_conversations": 142,
  "active_conversations": 3,
  "escalated_conversations": 18,
  "resolved_conversations": 121,
  "total_turns": 890,
  "total_input_tokens": 1200000,
  "total_output_tokens": 95000,
  "total_cost_usd": 1.34,
  "tool_calls_total": 210,
  "tool_calls_success": 198,
  "model_breakdown": [
    { "model": "gpt-4o-mini", "calls": 890, "cost_usd": 1.34 }
  ]
}
```

**UI design — show as stat cards:**

| Card | Value |
|---|---|
| Total Conversations | `total_conversations` |
| Active Now | `active_conversations` |
| Escalated | `escalated_conversations` with `%` of total |
| Resolved | `resolved_conversations` |
| Total Turns | `total_turns` |
| Tool Success Rate | `(tool_calls_success / tool_calls_total) * 100` % |
| Total Cost | `$total_cost_usd` formatted to 4 decimal places |

Under the cards, show a **Model Breakdown** table with model name, call count, and cost.

---

## 4. Tab 2 — AI Config

This tab lets the workspace owner configure which AI provider to use and the API key.

### 4.1 Fetch Current Config

```
GET /api/workspace/ai-config
Authorization: Bearer <token>
```

**Response:**
```json
{
  "ai_provider": "openai",
  "ai_model": "gpt-4o-mini",
  "has_api_key": true
}
```
> Note: The API key itself is never returned. Only `has_api_key: true/false` is returned.

**On page load:** call this and pre-fill the form. Show `"sk-..."` as placeholder in the API key field (never real key). Show "Current provider: openai · Model: gpt-4o-mini" below the form.

### 4.2 Save Config

```
PUT /api/workspace/ai-config
Authorization: Bearer <token>
Content-Type: application/json

{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key": "sk-..."
}
```

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `provider` | string | Yes | Dropdown: `openai`, `google`, `groq`, `anthropic` |
| `model` | string | Yes | Text input. Per-provider suggestions below. |
| `api_key` | string | No | Leave blank to keep the existing key. Only send if changed. |

**Suggested models per provider** (show as hints or datalist):

| Provider | Suggested Models |
|---|---|
| openai | `gpt-4o-mini`, `gpt-4o`, `gpt-3.5-turbo` |
| google | `gemini-2.0-flash`, `gemini-1.5-pro`, `gemini-1.5-flash` |
| groq | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` |
| anthropic | `claude-haiku-4-5-20251001`, `claude-sonnet-4-5`, `claude-opus-4-5` |

**On success:** show toast: *"AI configuration saved."* Update the "Current provider / Model" line below the form.

**Important note on `api_key`:** If the user leaves the API key field blank, do NOT send the `api_key` field in the request body (or send `null`). The backend will keep the existing key.

---

## 5. Tab 3 — AI Pipeline

This tab controls how AI processes incoming messages.

### 5.1 Fetch Current Pipeline Config

```
GET /api/workspace/ai-pipeline
Authorization: Bearer <token>
```

**Response:**
```json
{
  "ai_mode": "ai_agent",
  "rag_enabled": true,
  "escalation_enabled": true,
  "response_style": "friendly",
  "confidence_threshold": 0.7
}
```

Pre-fill all fields on page load.

### 5.2 Save Pipeline Config

```
PUT /api/workspace/ai-pipeline
Authorization: Bearer <token>
Content-Type: application/json

{
  "ai_mode": "ai_agent",
  "rag_enabled": true,
  "escalation_enabled": true,
  "response_style": "friendly",
  "confidence_threshold": 0.7
}
```

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `ai_mode` | string | Yes | **Critical field.** `"rag"` or `"ai_agent"`. This is the master switch. |
| `rag_enabled` | boolean | Yes | Toggle. When true, knowledge base documents are used in RAG mode. |
| `escalation_enabled` | boolean | Yes | Toggle. When false, AI never escalates — always tries to answer. |
| `response_style` | string | No | Dropdown: `friendly`, `professional`, `concise`, `empathetic` |
| `confidence_threshold` | float | No | 0.0–1.0 slider. Below this, AI escalates. |

**The `ai_mode` field is the most important one in the whole AI Studio.** Make sure it's prominently displayed. Suggested UI: a large segmented control or radio card group:

```
┌─────────────────────────────────────────────┐
│  AI Mode                                     │
│  ● RAG Mode          ○ AI Agent Mode         │
│  Uses uploaded         Uses configured AI    │
│  knowledge base        Agents per channel    │
└─────────────────────────────────────────────┘
```

**Contextual help text:**
- **RAG Mode:** "AI answers questions using your uploaded documents. Best for FAQ and knowledge base bots."
- **AI Agent Mode:** "AI uses your configured AI Agents to handle conversations. Supports tools, escalation, and custom personas."

**Show "Current" status line** below the form (from the fetched config):
> `Current: RAG on · Escalation on · Style: friendly · Threshold: 0.70`

**On success:** show toast: *"Pipeline settings saved."*

---

## 6. Shared Concepts

### 6.1 Agent Lifecycle

```
Create Agent (is_draft=true)
        │
        ├─ Add tools
        ├─ Add guardrails
        ├─ Assign to channels
        ├─ Test in Sandbox
        │
        ▼
   Publish Agent (is_draft=false)
        │
        ▼
   Agent is LIVE — handles messages on assigned channels
```

Never show the Publish button if `is_draft = false` (already live).

### 6.2 Draft vs Live

| State | `is_draft` | Handles messages? | Badge |
|---|---|---|---|
| Draft | `true` | No | Yellow "DRAFT" |
| Live | `false` | Yes | Green "LIVE" |

### 6.3 Publish Validation

The backend enforces these rules before publishing. The `POST /api/ai-agents/{id}/publish` endpoint returns a `400` with a message if any are missing:
- `system_prompt` must not be empty
- `escalation_message` must not be empty
- At least 1 active tool must exist

Show the backend's error message directly to the user — it will already be human-readable.

### 6.4 Agent Tone Options

Use these consistent options everywhere a "tone" or "response style" is offered:
- `friendly` — Warm and conversational
- `professional` — Formal and precise
- `empathetic` — Understanding and compassionate
- `concise` — Short and direct

---

## 7. Auth & Headers

Every request must include:
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

The token comes from the login response and is stored in memory (not localStorage).

On `401` response: call `POST /api/auth/refresh` to get a new token and retry the original request. If refresh also fails, redirect to login.

---

## 8. Error Handling

| HTTP Status | What it means | What to show |
|---|---|---|
| `400` | Validation error | Show the `detail` field from the response as an inline error below the relevant field |
| `401` | Unauthorized | Refresh token, retry. If fails → redirect to login |
| `402` | Feature requires paid tier | Show upgrade prompt with tier info |
| `404` | Resource not found | Show "Not found" state, navigate back to list |
| `422` | Schema validation failed | Show field-level error from `detail[].msg` |
| `500` | Server error | Show generic error toast: *"Something went wrong. Please try again."* |

Error response shape for `400`/`422`:
```json
{ "detail": "Agent must have at least one active tool before publishing." }
```
or for `422`:
```json
{
  "detail": [
    { "loc": ["body", "name"], "msg": "field required", "type": "value_error.missing" }
  ]
}
```

---

## 9. Tier Gating

AI Agents are restricted by workspace tier:

| Tier | Max AI Agents |
|---|---|
| Free | 0 (no access) |
| Starter | 1 |
| Growth | 3 |
| Pro | 10 |

Check `GET /api/billing/status` for current tier and usage.

**When tier is `free`:** Show a locked/blurred state on the AI Agents tab with:
> *"AI Agents require Starter plan or above."*
> [Upgrade button]

**When agent limit is reached:** The `POST /api/ai-agents` will return `402` with:
> *"AI agent limit (1) reached for starter tier."*
Show an inline message: *"You've reached your agent limit. Upgrade to Growth for 3 agents."*

---

## 10. Current UI Bugs to Fix

These are issues visible in the current screenshots:

### Bug 1 — AI Config "Current provider / Model" shows blank
**Problem:** The text reads `"Current provider: · Model:"` with no values.
**Fix:** On component mount, call `GET /api/workspace/ai-config` and set state with `ai_provider` and `ai_model`. Display them in the status line.

### Bug 2 — AI Pipeline status line shows blank values
**Problem:** `"Current: RAG off · Escalation off · · threshold"` — response style and threshold are empty.
**Fix:** On mount, call `GET /api/workspace/ai-pipeline` and populate all fields from the response. The `confidence_threshold` field may be `null` — show `"not set"` if null.

### Bug 3 — `ai_mode` field missing from AI Pipeline tab
**Problem:** There is no `ai_mode` toggle in the current UI. This field controls whether the system uses RAG or AI Agents — it's the most important field.
**Fix:** Add a prominent mode selector (radio cards or segmented control) for `ai_mode: "rag" | "ai_agent"`. Include it in the save payload.

### Bug 4 — No agent list view
**Problem:** Clicking "New Agent" shows the create form, but there is no list of existing agents shown anywhere.
**Fix:** The default view of the AI Agents tab should be the agents list. "New Agent" button opens the create form (as a modal or navigates to a new-agent page).

### Bug 5 — Model field in "Create AI Agent" form
**Problem:** Model field is currently a free text input showing `gpt-4o-mini`.
**Note:** This field is not actually part of the agent — the agent uses the workspace's AI Config provider/model. The Model field in the create form may be a leftover from an earlier design. **Do not send a `model` field when creating/updating an agent** — there is no such field in the backend schema. Remove it from the form or clarify if it's a future feature.

---

## Quick Reference — All AI Studio API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/workspace/ai-config` | Get current AI provider + model |
| `PUT` | `/api/workspace/ai-config` | Save AI provider, model, API key |
| `GET` | `/api/workspace/ai-pipeline` | Get pipeline settings |
| `PUT` | `/api/workspace/ai-pipeline` | Save pipeline settings incl. ai_mode |
| `GET` | `/api/ai-agents` | List all AI agents |
| `POST` | `/api/ai-agents` | Create new agent |
| `GET` | `/api/ai-agents/{id}` | Get single agent (includes tools + guardrails) |
| `PUT` | `/api/ai-agents/{id}` | Update agent |
| `DELETE` | `/api/ai-agents/{id}` | Delete agent |
| `POST` | `/api/ai-agents/{id}/publish` | Publish draft agent to live |
| `GET` | `/api/ai-agents/{id}/tools` | List tools |
| `POST` | `/api/ai-agents/{id}/tools` | Create tool |
| `PUT` | `/api/ai-agents/{id}/tools/{tool_id}` | Update tool |
| `DELETE` | `/api/ai-agents/{id}/tools/{tool_id}` | Delete tool |
| `POST` | `/api/ai-agents/{id}/tools/{tool_id}/test` | Test tool with params |
| `GET` | `/api/ai-agents/{id}/guardrails` | List guardrails |
| `POST` | `/api/ai-agents/{id}/guardrails` | Add guardrail |
| `DELETE` | `/api/ai-agents/{id}/guardrails/{guardrail_id}` | Delete guardrail |
| `POST` | `/api/ai-agents/{id}/channels/{channel_id}` | Assign agent to channel |
| `DELETE` | `/api/ai-agents/{id}/channels/{channel_id}` | Unassign agent from channel |
| `POST` | `/api/ai-agents/{id}/sandbox/message` | Send test message in sandbox |
| `DELETE` | `/api/ai-agents/{id}/sandbox/reset` | Reset sandbox session |
| `GET` | `/api/ai-agents/{id}/analytics` | Get token usage + performance stats |
