# Assignment Rules

Assignment Rules is a **Pro-tier feature** that automatically routes incoming conversations to human agents based on configurable conditions and strategies. Instead of conversations landing in a generic queue, rules let you define precise routing logic — send WhatsApp billing complaints to a specific agent, distribute general inquiries round-robin, or always pick the least busy agent.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Rule Anatomy](#rule-anatomy)
- [Routing Actions](#routing-actions)
- [Conditions Reference](#conditions-reference)
- [Priority System](#priority-system)
- [Escalation Integration](#escalation-integration)
- [Fallback Behavior](#fallback-behavior)
- [API Reference](#api-reference)
- [Tier Availability](#tier-availability)
- [Examples](#examples)

---

## How It Works

Assignment rules are evaluated **at the moment a conversation is escalated** (either automatically by the AI classifier or manually). The system runs through every active rule in priority order and applies the first one that matches.

```
Incoming message
      │
      ▼
AI classifier / manual escalation trigger
      │
      ▼
evaluate_rules()  ← iterates active rules ordered by priority (ASC)
      │
      ├─ rule matches? → assign_by_rule() → update conversation.assigned_agent_id
      │
      └─ no match → FIFO fallback (oldest created_at agent)
```

The matching and assignment logic lives in:
- `backend/app/services/assignment_service.py` — rule evaluation and agent selection
- `backend/app/services/escalation_router.py` — orchestrates the full escalation + assignment flow

---

## Rule Anatomy

Each rule has the following fields:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Auto-generated rule ID |
| `workspace_id` | UUID | Workspace this rule belongs to |
| `name` | string (1–100 chars) | Human-readable label |
| `priority` | int (1–1000) | Lower number = evaluated first |
| `conditions` | JSON object | Criteria the conversation must match |
| `action` | enum | Routing strategy to apply |
| `target_agent_id` | UUID \| null | Required when `action = specific_agent` |
| `is_active` | boolean | Toggle without deleting the rule |
| `created_at` | ISO timestamp | Auto-set on creation |

---

## Routing Actions

Three routing strategies are supported:

### `specific_agent`
Routes to a single named agent. The target agent must be **online** and **active** at the time of assignment. If the agent is offline, no assignment is made (falls through to fallback).

```json
{
  "action": "specific_agent",
  "target_agent_id": "<agent-uuid>"
}
```

### `round_robin`
Picks the online agent who has been idle the longest (approximated by `last_heartbeat_at ASC`). Distributes load evenly across available agents over time.

```json
{
  "action": "round_robin"
}
```

### `least_loaded`
Counts active conversations per agent (status `escalated` or `agent`) and picks the online agent with the fewest. Ensures no single agent gets overloaded.

```json
{
  "action": "least_loaded"
}
```

---

## Conditions Reference

The `conditions` field is a JSON object. **All specified conditions must match** for a rule to apply. An empty `{}` conditions object matches every conversation.

### `keywords`
Matches if any keyword appears (case-insensitive) in the escalation reason or message content.

```json
{
  "keywords": ["billing", "refund", "invoice"]
}
```

### `channel_type`
Matches a specific channel. Must be an exact string match.

```json
{
  "channel_type": "whatsapp"
}
```

Common values: `whatsapp`, `webchat`, `instagram`, `telegram`

### Combining conditions
All conditions are AND-ed. The rule below only matches WhatsApp conversations that mention "billing":

```json
{
  "keywords": ["billing"],
  "channel_type": "whatsapp"
}
```

---

## Priority System

Priority is a number between **1 and 1000** (default: 100). Rules are evaluated in **ascending order** — priority 1 is checked first, priority 1000 last.

```
Priority 1   ← checked first
Priority 10
Priority 100 ← default
Priority 500
Priority 1000 ← checked last
```

The **first matching rule wins** — remaining rules are not evaluated. Design your rules from most specific (low priority number) to most general (high priority number).

**Example ordering:**
```
Priority  10 — WhatsApp + billing keyword → specific agent (Sarah)
Priority  50 — WhatsApp only             → round_robin
Priority 100 — any channel              → least_loaded
```

---

## Escalation Integration

Assignment rules are applied inside `EscalationRouter.process_escalation()`:

1. Conversation status is set to `escalated`
2. A system message documents the escalation reason
3. Active agents for the workspace are fetched
4. **`assignment_service.evaluate_rules()` is called** with the workspace ID, escalation reason text, and channel type
5. If a rule matches, **`assignment_service.assign_by_rule()`** executes the routing action
6. If no rule matches (or the matched rule returns no agent), the system falls back to FIFO
7. `conversation.assigned_agent_id` is persisted
8. Customer acknowledgment is sent; agents are notified via WebSocket

The escalation reason passed to rule evaluation is either:
- `"explicit"` — customer directly asked for a human
- `"implicit"` — AI inferred escalation was needed
- `"direct_routing"` — AI is disabled in workspace settings

---

## Fallback Behavior

If no rule matches (or a matched rule's target agent is unavailable), the system falls back to **FIFO assignment** — the agent with the earliest `created_at` timestamp who is online and active.

If **no agents are online at all**, the conversation remains unassigned and:
- The workspace owner receives an email alert (if `escalation_email_enabled = true`)
- The customer receives a "we'll follow up via email" acknowledgment message

---

## API Reference

All endpoints require authentication (`Authorization: Bearer <token>`) and a `X-Workspace-ID` header. **Pro tier only** — non-Pro workspaces receive `402 Payment Required`.

---

### `GET /api/assignment-rules`

List all assignment rules for the workspace, ordered by priority ascending.

**Response `200`**
```json
[
  {
    "id": "3fa85f64-...",
    "workspace_id": "1c2d3e...",
    "name": "Billing to Sarah",
    "priority": 10,
    "conditions": { "keywords": ["billing"], "channel_type": "whatsapp" },
    "action": "specific_agent",
    "target_agent_id": "agent-uuid",
    "is_active": true,
    "created_at": "2026-01-15T10:00:00+00:00"
  }
]
```

---

### `POST /api/assignment-rules`

Create a new assignment rule.

**Request body**
```json
{
  "name": "Billing to Sarah",
  "priority": 10,
  "conditions": {
    "keywords": ["billing", "refund"],
    "channel_type": "whatsapp"
  },
  "action": "specific_agent",
  "target_agent_id": "<agent-uuid>",
  "is_active": true
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | 1–100 characters |
| `action` | Yes | `round_robin`, `specific_agent`, or `least_loaded` |
| `priority` | No | Default: 100 |
| `conditions` | No | Default: `{}` (matches everything) |
| `target_agent_id` | Conditional | Required when `action = specific_agent` |
| `is_active` | No | Default: `true` |

**Response `201`** — returns the created rule object.

**Errors**
- `402` — workspace is not on Pro tier
- `422` — validation error (invalid action value, priority out of 1–1000 range, etc.)

---

### `PUT /api/assignment-rules/{rule_id}`

Update an existing rule. All fields are optional — only send what you want to change.

**Request body** (all optional)
```json
{
  "name": "Billing & Refunds to Sarah",
  "priority": 5,
  "conditions": { "keywords": ["billing", "refund", "invoice"] },
  "action": "specific_agent",
  "target_agent_id": "<agent-uuid>",
  "is_active": true
}
```

**Response `200`** — returns the updated rule object.

**Errors**
- `402` — not Pro tier
- `404` — rule not found in this workspace

---

### `DELETE /api/assignment-rules/{rule_id}`

Delete a rule permanently.

**Response `204`** — no body.

**Errors**
- `402` — not Pro tier
- `404` — rule not found in this workspace

---

## Tier Availability

| Tier | Price | Assignment Rules |
|---|---|---|
| Free | $0 | No |
| Starter | $15/mo | No |
| Growth | $29/mo | No |
| **Pro** | **$59/mo** | **Yes** |

Attempting any endpoint on a non-Pro workspace returns:
```json
{
  "detail": "Assignment rules require Pro tier. Please upgrade."
}
```

---

## Examples

### Example 1 — Route billing complaints to a specialist

```json
{
  "name": "Billing specialist",
  "priority": 10,
  "conditions": { "keywords": ["billing", "payment", "invoice", "refund"] },
  "action": "specific_agent",
  "target_agent_id": "<sarah-agent-id>"
}
```

### Example 2 — WhatsApp gets round-robin

```json
{
  "name": "WhatsApp distribution",
  "priority": 50,
  "conditions": { "channel_type": "whatsapp" },
  "action": "round_robin"
}
```

### Example 3 — All other conversations go to least loaded

```json
{
  "name": "Default least-loaded",
  "priority": 999,
  "conditions": {},
  "action": "least_loaded"
}
```

Together, these three rules form a layered routing policy. Rules 1 and 2 handle specific scenarios; Rule 3 is the catch-all. Any conversation not matched by the first two falls through to the least-loaded strategy.

### Example 4 — Temporarily disable a rule without deleting

```http
PUT /api/assignment-rules/<rule-id>
Content-Type: application/json

{
  "is_active": false
}
```

The rule is preserved but skipped during evaluation until re-enabled.
