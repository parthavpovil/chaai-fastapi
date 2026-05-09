# Chat Widget: Complete Message Flow Documentation

This document describes everything that happens when a customer sends a message through the chat widget — every branch, every feature flag, every scenario.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Key Files & Services](#key-files--services)
3. [Configuration Flags](#configuration-flags)
4. [Phase 1 — Message Ingestion (Always Runs)](#phase-1--message-ingestion-always-runs)
5. [Phase 2 — Routing Decision](#phase-2--routing-decision)
6. [Scenario A — No AI, No Agents (Silent Reception)](#scenario-a--no-ai-no-agents-silent-reception)
7. [Scenario B — No AI, Agents Enabled (Direct Routing)](#scenario-b--no-ai-agents-enabled-direct-routing)
8. [Scenario C — AI Agent Mode](#scenario-c--ai-agent-mode)
9. [Scenario D — RAG Mode (Default AI)](#scenario-d--rag-mode-default-ai)
10. [Auto-Escalation: Deep Dive](#auto-escalation-deep-dive)
11. [RAG Pipeline: Deep Dive](#rag-pipeline-deep-dive)
12. [Escalation Processing: Deep Dive](#escalation-processing-deep-dive)
13. [WebSocket & Real-Time Events](#websocket--real-time-events)
14. [Token Tracking & Billing](#token-tracking--billing)
15. [Business Hours Handling](#business-hours-handling)
16. [Maintenance Mode](#maintenance-mode)
17. [Contact Blocking](#contact-blocking)
18. [Complete Decision Tree (All Scenarios Combined)](#complete-decision-tree-all-scenarios-combined)
19. [Database State Changes Per Scenario](#database-state-changes-per-scenario)
20. [Feature Flag Matrix](#feature-flag-matrix)

---

## Architecture Overview

```
Customer Widget
    │
    ├─ HTTP POST /api/webchat/send          ← message submission
    └─ WebSocket ws://.../ws/webchat/{wid}  ← receive replies in real-time

Backend Services
    ├─ MessageProcessor       (validate, deduplicate, store)
    ├─ EscalationClassifier   (keyword + LLM detection)
    ├─ EscalationRouter       (route to human agent)
    ├─ AIAgentRunner          (tool-calling AI agent)
    ├─ RAGEngine              (retrieval-augmented generation)
    ├─ WebSocketManager       (customer real-time push)
    ├─ RedisPubSub            (multi-worker broadcast)
    └─ AIAgentTokenTracker    (token logging + billing)
```

---

## Key Files & Services

| File | Purpose |
|------|---------|
| `app/routers/webchat.py` | HTTP endpoint — `POST /api/webchat/send` |
| `app/routers/websocket_webchat.py` | WebSocket endpoint for customer real-time events |
| `app/services/message_processor.py` | Ingestion, validation, deduplication |
| `app/services/escalation_classifier.py` | Keyword + LLM escalation detection |
| `app/services/escalation_router.py` | Escalation workflow orchestration |
| `app/services/rag_engine.py` | Full RAG pipeline |
| `app/services/ai_agent_runner.py` | AI agent execution + tool calling |
| `app/services/ai_agent_token_tracker.py` | Token usage logging + cost estimation |
| `app/services/websocket_events.py` | WebSocket broadcast helpers |
| `app/services/redis_pubsub.py` | Redis pub/sub for multi-worker delivery |
| `app/models/message.py` | Message DB model |
| `app/models/conversation.py` | Conversation DB model + status enum |
| `app/models/workspace.py` | Workspace config + feature flags |
| `app/models/ai_agent.py` | AI agent config + conversation tracking |

---

## Configuration Flags

Every routing decision is controlled by workspace-level settings. These are read at the start of each request.

| Flag | Location | Default | Values | Effect |
|------|----------|---------|--------|--------|
| `ai_enabled` | `workspace.ai_enabled` | `True` | Boolean | Disables **all** AI responses when `False` |
| `ai_mode` | `workspace.meta.ai_mode` | `"rag"` | `"rag"` / `"ai_agent"` | Selects AI pipeline |
| `agents_enabled` | `workspace.agents_enabled` | `False` | Boolean | Enables human agent routing |
| `auto_escalation_enabled` | `workspace.auto_escalation_enabled` | `True` | Boolean | Enables escalation classifier |
| `escalation_keywords` | `workspace.escalation_keywords` | `null` | JSONB array | Custom keywords; `null` = use built-in defaults |
| `escalation_sensitivity` | `workspace.escalation_sensitivity` | `"medium"` | `"low"` / `"medium"` / `"high"` | Controls escalation confidence threshold |
| `escalation_email_enabled` | `workspace.escalation_email_enabled` | `True` | Boolean | Email owner when no agents are available |
| `escalation_message_with_agents` | `workspace` | `null` | Text | Custom acknowledgment text when agents assigned |
| `escalation_message_without_agents` | `workspace` | `null` | Text | Custom acknowledgment text when no agents |
| `outside_hours_behavior` | `workspace` | `"inform_and_continue"` | `"inform_and_pause"` / `"inform_and_continue"` | What to do outside business hours |
| `outside_hours_message` | `workspace` | `null` | Text | Custom outside-hours message |
| `fallback_msg` | `workspace` | `"Sorry, I couldn't find..."` | Text | RAG fallback when no knowledge chunks found |
| `maintenance_mode` | `PlatformSetting` | `"false"` | `"true"` / `"false"` | Platform-wide maintenance mode |
| `max_turns` | `AIAgent` | `10` | Integer | Max conversation turns before AI agent escalates |
| `token_budget` | `AIAgent` | `8000` | Integer | LLM context window size in tokens |
| `is_active` | `AIAgent` | `True` | Boolean | Whether the AI agent is active |
| `is_draft` | `AIAgent` | `True` | Boolean | Draft agents are never used |

---

## Phase 1 — Message Ingestion (Always Runs)

This phase runs for **every single message**, regardless of any feature flags.

```
POST /api/webchat/send
    │
    ├─ 1. Validate widget_id
    │      └─ Look up WebChat channel by widget_id
    │         └─ FAIL → 404 Not Found
    │
    ├─ 2. Session Token
    │      └─ Use provided session_token OR generate a new UUID
    │
    ├─ 3. Rate Limiting
    │      └─ Check per session_token rate limit
    │         └─ EXCEED → 429 Too Many Requests
    │
    ├─ 4. MessageProcessor.preprocess_message()
    │      │
    │      ├─ 4a. Maintenance Mode Check
    │      │      └─ PlatformSetting "maintenance_mode" == "true"
    │      │         └─ RETURN: maintenance error message (no storage)
    │      │
    │      ├─ 4b. Message Deduplication
    │      │      └─ Check external_message_id in DB
    │      │         └─ DUPLICATE → return existing message silently
    │      │
    │      ├─ 4c. Tier Limit Check
    │      │      └─ TierManager.check_monthly_message_limit(workspace)
    │      │         └─ EXCEEDED → return quota exceeded error
    │      │
    │      ├─ 4d. Contact Resolution
    │      │      └─ Get or create Contact by (workspace_id + channel_id + external_id)
    │      │
    │      ├─ 4e. Contact Block Check
    │      │      └─ contact.is_blocked == True
    │      │         └─ RETURN: silent (no response, no storage of reply)
    │      │
    │      ├─ 4f. Conversation Resolution
    │      │      └─ Get active conversation OR create new one (status="active")
    │      │
    │      ├─ 4g. Business Hours Check
    │      │      └─ (see Business Hours section below)
    │      │
    │      ├─ 4h. Store Customer Message
    │      │      └─ Create Message(role="customer", content=..., channel_type="webchat")
    │      │
    │      └─ 4i. Fire Webhooks (async, non-blocking)
    │             ├─ trigger_event("conversation.created") — first message only
    │             └─ trigger_event("message.received")
    │
    └─ → Continue to Phase 2: Routing
```

**What is always stored:**
- `Message` row with `role="customer"`
- `Contact` row (upserted)
- `Conversation` row (upserted, `status="active"`)

**What is NOT stored if blocked/maintenance/duplicate:**
- No assistant reply is saved
- No escalation is triggered

---

## Phase 2 — Routing Decision

After ingestion, the system reads workspace config and picks a routing path:

```
Read workspace config
    │
    ├─ ai_enabled == False
    │      ├─ agents_enabled == True  → Scenario B (Direct Routing)
    │      └─ agents_enabled == False → Scenario A (Silent Reception)
    │
    └─ ai_enabled == True
           ├─ meta.ai_mode == "ai_agent" → Scenario C (AI Agent Mode)
           └─ meta.ai_mode == "rag"      → Scenario D (RAG Mode)
```

---

## Scenario A — No AI, No Agents (Silent Reception)

**Config:** `ai_enabled=False`, `agents_enabled=False`

```
Customer message arrives
    │
    └─ Phase 1 runs (store message, fire webhooks)
    │
    └─ No response generated
       No escalation triggered
       No agent notified

Customer receives: nothing (silence)
Conversation stays at: status="active"
```

**Use case:** Workspace is configured as a simple inbox. Messages are collected but no automated responses or routing occurs.

---

## Scenario B — No AI, Agents Enabled (Direct Routing)

**Config:** `ai_enabled=False`, `agents_enabled=True`

```
Customer message arrives
    │
    └─ Phase 1 runs
    │
    └─ EscalationRouter.process_escalation(reason="direct_routing")
           │
           ├─ 1. Update conversation.status = "escalated"
           │
           ├─ 2. Create system Message(role="system", escalation_reason="direct_routing")
           │
           ├─ 3. Agent Assignment
           │      ├─ Load available agents (status="online")
           │      ├─ Evaluate AssignmentRules (if any configured)
           │      └─ Fallback: assign to first agent (FIFO by created_at)
           │         └─ No agents available? → skip assignment, log, email owner (if escalation_email_enabled)
           │
           ├─ 4. Set conversation.assigned_agent_id = agent.id
           │
           ├─ 5. Send acknowledgment Message(role="assistant")
           │      └─ Uses workspace.escalation_message_with_agents OR
           │         workspace.escalation_message_without_agents (if no agents)
           │         OR built-in defaults
           │
           ├─ 6. Notify agents via WebSocket (notify_escalation event)
           │
           ├─ 7. Notify customer via WebSocket (new_message event with acknowledgment)
           │
           └─ 8. Fire webhook: trigger_event("conversation.escalated") [async]

Customer receives: acknowledgment message in real-time
Conversation status: "escalated"
Agent receives: escalation WebSocket event
```

---

## Scenario C — AI Agent Mode

**Config:** `ai_enabled=True`, `meta.ai_mode="ai_agent"`

```
Customer message arrives
    │
    └─ Phase 1 runs
    │
    └─ AIAgentRunner.run()
           │
           ├─ 1. Find AI Agent assigned to this channel (AIAgentChannelAssignment)
           │      └─ Not found → fall through to RAG (Scenario D) or return nothing
           │
           ├─ 2. Check agent.is_active and NOT agent.is_draft
           │      └─ Inactive → fall through
           │
           ├─ 3. Get or create AIAgentConversation session
           │
           ├─ 4. Check max_turns limit (agent.max_turns, default 10)
           │      └─ Exceeded → escalate with reason="max_turns_exceeded"
           │         └─ Continue to Escalation Processing (below)
           │
           ├─ 5. Load conversation history (last 50 messages)
           │
           ├─ 6. Build tool schemas for all active tools on this agent
           │
           ├─ 7. Trim messages to token_budget (agent.token_budget, default 8000)
           │
           ├─ 8. Call LLM (temperature=0.3)
           │      └─ Provider/model is set on the agent config
           │
           ├─ 9. If LLM requested a tool call:
           │      ├─ Execute via ToolExecutor
           │      ├─ Log tool call (name, latency_ms, success)
           │      └─ Feed result back to LLM
           │
           ├─ 10. Log token usage → ai_agent_token_log + usage_counter
           │       └─ call_type = "response_generation"
           │
           ├─ 11. Increment AIAgentConversation.turn_count
           │
           ├─ 12. Check response for ESCALATE: prefix
           │       └─ If present → extract escalation_reason, escalate
           │          └─ Continue to Escalation Processing (below)
           │
           └─ 13. If NOT escalated:
                  ├─ Create Message(role="assistant", content=reply)
                  ├─ Notify agents via WebSocket (notify_new_message)
                  ├─ Notify customer via WebSocket (new_message event)
                  └─ Fire outbound webhooks [async]

Customer receives: AI agent reply in real-time
Conversation status: stays "active" (until escalated)
AIAgentConversation: turn_count incremented
```

**If the AI Agent escalates** (via `ESCALATE:` prefix or `max_turns_exceeded`):

```
    └─ auto_escalation_enabled check STILL runs on top:
           └─ If also triggers keyword escalation → escalate (same outcome)
    └─ EscalationRouter.process_escalation() (see Escalation Processing below)
```

**Sub-scenarios within AI Agent mode:**

| Condition | Outcome |
|-----------|---------|
| Agent not found / inactive | Fall through to Scenario D (RAG) |
| Agent `is_draft=True` | Not used, fall through |
| `max_turns` exceeded | Escalate immediately |
| LLM returns `ESCALATE:` prefix | Escalate with extracted reason |
| Tool call fails | Error logged, agent may try without tool or escalate |
| Normal completion | Reply sent to customer |

---

## Scenario D — RAG Mode (Default AI)

**Config:** `ai_enabled=True`, `meta.ai_mode="rag"` (or `ai_agent` mode fell through)

```
Customer message arrives
    │
    └─ Phase 1 runs
    │
    └─ AUTO-ESCALATION CHECK (if auto_escalation_enabled == True)
           │
           ├─ Should escalate? → Escalation Processing (see below)
           │   └─ Customer receives: acknowledgment
           │
           └─ Not escalated → RAG PIPELINE
                  │
                  └─ RAGEngine.process_rag_query()
                         │
                         └─ (see RAG Pipeline: Deep Dive below)
```

---

## Auto-Escalation: Deep Dive

**Triggered:** When `auto_escalation_enabled=True` and the conversation is in RAG mode (or AI Agent escalated).

```
EscalationClassifier.classify_message(message, workspace)
    │
    ├─ STEP 1: Keyword Detection
    │      │
    │      ├─ Use workspace.escalation_keywords if set
    │      │   OR use built-in defaults:
    │      │      Tier 1 (explicit): human, agent, manager, supervisor,
    │      │                         person, representative, speak to someone
    │      │      Tier 2 (emotional): frustrated, angry, upset, disappointed,
    │      │                          terrible, awful, unacceptable
    │      │      Tier 3 (urgent): urgent, emergency, asap, immediately, critical
    │      │      Tier 4 (legal): complaint, complain, refund, cancel, dispute,
    │      │                      lawyer, legal, sue
    │      │
    │      ├─ If keyword found:
    │      │      └─ escalation_type = "explicit"
    │      │         confidence = boosted (min 0.6)
    │      │
    │      └─ Log keyword detection
    │
    ├─ STEP 2: LLM Classification (if LLM available)
    │      │
    │      ├─ Send message to LLM with system prompt:
    │      │      "Classify if this needs human escalation.
    │      │       Return JSON: {should_escalate, confidence, category, type}"
    │      │
    │      ├─ Categories returned:
    │      │      - "technical_complexity"
    │      │      - "emotional_distress"
    │      │      - "explicit_request"
    │      │      - "billing_dispute"
    │      │      - "legal_threat"
    │      │      - "none"
    │      │
    │      ├─ Log tokens: call_type="escalation_check"
    │      │
    │      └─ Combine with keyword result:
    │             - Keyword AND LLM both agree → highest confidence
    │             - Keyword found, LLM disagrees → keyword wins (explicit)
    │             - LLM only → use LLM confidence
    │
    ├─ STEP 3: Apply Sensitivity Threshold
    │      │
    │      ├─ sensitivity multipliers:
    │      │      "low"    → threshold = 0.78 (harder to escalate)
    │      │      "medium" → threshold = 0.60 (default)
    │      │      "high"   → threshold = 0.42 (easier to escalate)
    │      │
    │      └─ if confidence < threshold → should_escalate = False
    │
    └─ Return:
           {should_escalate: bool, confidence: float, category: str, escalation_type: str}
```

**Sensitivity scenarios:**

| Sensitivity | Threshold | Effect |
|------------|-----------|--------|
| `low` | 0.78 | Only very obvious escalation signals trigger (fewer escalations) |
| `medium` | 0.60 | Balanced — default behavior |
| `high` | 0.42 | Small frustration signals trigger escalation (more escalations) |

---

## RAG Pipeline: Deep Dive

**Triggered:** `ai_enabled=True`, `ai_mode="rag"`, auto-escalation did NOT fire.

```
RAGEngine.process_rag_query(workspace, conversation_id, user_message)
    │
    ├─ STEP 1: Parallel Context Gathering
    │      │
    │      ├─ Conversation data:
    │      │      ├─ Load last 10 messages (CONTEXT_MESSAGES=10)
    │      │      └─ If conversation has ≥20 messages:
    │      │             └─ Generate/load conversation summary
    │      │
    │      └─ Workspace persona:
    │             ├─ workspace.fallback_msg
    │             ├─ workspace.assistant_name
    │             └─ workspace.assistant_persona
    │
    ├─ STEP 2: Small-Talk Detection
    │      └─ If message matches: hi, hello, hey, thanks, thank you, bye,
    │                             goodbye, ok, okay, yes, no, sure, np
    │         └─ SKIP embedding + search
    │            search_method = "small_talk"
    │            → go directly to LLM with just conversation context
    │
    ├─ STEP 3: Query Rewriting (if history exists)
    │      └─ LLM call to resolve coreferences:
    │            Input:  "Previous: [history]. Latest: what about it?"
    │            Output: "refund for duplicate Pro subscription charge"
    │            Tokens: logged as call_type="rag_rewrite"
    │
    ├─ STEP 4: Embedding Generation (cached)
    │      └─ Generate vector for rewritten query
    │         Model: text-embedding-3-small (1536 dimensions)
    │         Cache: LRU, 512 entries, key = (query + model)
    │
    ├─ STEP 5: Hybrid Search — BM25 + Vector + RRF
    │      │
    │      ├─ Vector Search (pgvector cosine distance):
    │      │      ├─ Primary threshold: 0.35
    │      │      ├─ Fallback 1: 0.25
    │      │      ├─ Fallback 2: 0.18
    │      │      └─ Returns ranked list of chunks
    │      │
    │      ├─ BM25 Full-Text Search (PostgreSQL tsvector):
    │      │      ├─ Convert AND logic → OR (partial keyword matching)
    │      │      └─ Returns ranked list of chunks
    │      │
    │      └─ Reciprocal Rank Fusion (RRF_K=60):
    │             RRF_score = 1/(60 + rank_vector) + 1/(60 + rank_bm25)
    │             Return top-20 candidates
    │             search_method = "hybrid" | "vector_only" | "bm25_only" | "none"
    │
    ├─ STEP 6: MMR Re-ranking (Diversity)
    │      └─ Maximum Marginal Relevance:
    │            lambda = 0.7 (70% relevance, 30% diversity)
    │            Select top-5 most relevant + diverse chunks
    │
    ├─ STEP 7: Neighbor Expansion
    │      └─ For each selected chunk:
    │            Fetch adjacent chunks (before + after in document)
    │            Provides broader reading context
    │
    ├─ STEP 8: LLM Generation
    │      │
    │      ├─ System prompt:
    │      │      - "Answer ONLY from the provided passages"
    │      │      - "Cite sources with [N] after every claim"
    │      │      - "If passages are insufficient, use the fallback message"
    │      │      - "Special handling for greetings — don't use fallback"
    │      │      - "Special handling for meta-questions — don't use fallback"
    │      │
    │      ├─ Context includes (in order):
    │      │      1. [Conversation summary] — if available
    │      │      2. [Knowledge base] — numbered passages
    │      │      3. [Recent conversation] — last N turns
    │      │      4. "Customer: {query}\nAssistant:"
    │      │
    │      ├─ Temperature: 0.4 (factual, low creativity)
    │      ├─ Max tokens: 300
    │      │
    │      └─ Log tokens: call_type="rag_response"
    │
    ├─ STEP 9: No Chunks Found — Fallback Decision
    │      └─ If used_fallback == True (search returned nothing relevant):
    │             │
    │             ├─ auto_escalation_enabled == True:
    │             │      └─ Escalate with reason="RAG knowledge base could not answer"
    │             │         → Send escalation acknowledgment to customer
    │             │
    │             └─ auto_escalation_enabled == False:
    │                    └─ Return workspace.fallback_msg as assistant reply
    │
    └─ Return:
           response, input_tokens, output_tokens,
           relevant_chunks_count, chunks_used,
           has_conversation_context, used_fallback,
           search_method, threshold_used
```

**Post-RAG (successful response):**
```
    ├─ Create Message(role="assistant", metadata={rag_used:true, tokens, search_method})
    ├─ Notify agents via WebSocket: notify_new_message()
    ├─ Notify customer via WebSocket: new_message event
    └─ Fire outbound webhooks [async]
```

**RAG sub-scenarios:**

| Condition | Outcome |
|-----------|---------|
| Small-talk detected | Skip RAG search, LLM answers directly from context |
| Strong search results (hybrid) | Normal RAG response with citations |
| Vector-only results | RAG response, `search_method="vector_only"` |
| BM25-only results | RAG response, `search_method="bm25_only"` |
| No results + escalation on | Escalate to human agent |
| No results + escalation off | Return workspace fallback message |
| First message (no history) | No query rewriting step |

---

## Escalation Processing: Deep Dive

**Called by:** Direct routing (Scenario B), AI Agent escalation, Auto-escalation, RAG fallback escalation.

```
EscalationRouter.process_escalation(
    conversation, workspace, escalation_reason, escalation_type, confidence
)
    │
    ├─ 1. Update conversation.status = "escalated"
    │      └─ Set conversation.escalation_reason = reason
    │         Set conversation.metadata with confidence + category
    │
    ├─ 2. Create Message(role="system")
    │      └─ Content: structured escalation metadata
    │         metadata.escalation_reason, escalation_type, confidence, category
    │
    ├─ 3. Agent Assignment
    │      │
    │      ├─ Load all agents with status="online" for this workspace
    │      │
    │      ├─ Evaluate AssignmentRules (if configured)
    │      │      └─ Rules can filter by: language, department, skill, tag
    │      │
    │      ├─ If rule matches → assign to targeted agent
    │      │
    │      └─ Fallback → assign to first available agent (FIFO by created_at)
    │
    ├─ 4. If agent assigned:
    │      └─ conversation.assigned_agent_id = agent.id
    │         conversation.status = "agent"
    │
    ├─ 5. If NO agents available:
    │      ├─ conversation stays "escalated" (unassigned)
    │      └─ escalation_email_enabled == True:
    │             └─ Send email to workspace.owner_email
    │                with: conversation link, customer name, reason
    │
    ├─ 6. Create acknowledgment Message(role="assistant")
    │      └─ Priority:
    │            1. workspace.escalation_message_with_agents (if agents available)
    │            2. workspace.escalation_message_without_agents (if no agents)
    │            3. Built-in default: "I've connected you with a human agent..."
    │
    ├─ 7. Notify agents via WebSocket: notify_escalation()
    │      └─ Event: "escalation" with conversation_id, priority, classification
    │
    ├─ 8. Notify customer via WebSocket: new_message (acknowledgment)
    │
    └─ 9. Fire webhook: trigger_event("conversation.escalated") [async]

Escalation reasons stored:
    - "direct_routing"         → no AI configured
    - "explicit"               → keyword detected
    - "implicit"               → LLM detected frustration/complexity
    - "max_turns_exceeded"     → AI agent hit turn limit
    - "agent_requested"        → AI agent decided to escalate
    - "rag_fallback"           → RAG had no answer
```

**After escalation — human agent takes over:**
```
Conversation status: "agent"
Assigned agent sees: full conversation history in dashboard
Human agent replies via: POST /api/conversations/{id}/messages
Customer receives: human agent messages via WebSocket
```

---

## WebSocket & Real-Time Events

### Customer WebSocket (`/ws/webchat/{workspace_id}`)

Connection params: `widget_id`, `session_token`

| Event | Payload | When Sent |
|-------|---------|-----------|
| `new_message` | `{message_id, role, content, msg_type, media_url, created_at}` | Every assistant/agent message |
| `conversation_status_changed` | `{new_status, agent_name, timestamp}` | On escalation or resolution |
| `csat_prompt` | `{token, expires_in_hours}` | After conversation resolved |

### Agent WebSocket (authenticated)

| Event | Payload | When Sent |
|-------|---------|-----------|
| `escalation` | `{conversation_id, escalation_reason, priority, classification}` | On any escalation |
| `new_message` | `{conversation_id, message_id, role, content, channel_type, created_at}` | Every message in workspace |
| `agent_status` | `{agent_id, status}` | Agent comes online/offline |
| `conversation_status_change` | `{conversation_id, old_status, new_status, agent}` | Any status transition |

### Delivery Mechanism (Redis Pub/Sub)

```
Event triggered
    │
    └─ Publish to Redis channel:
           ws:{workspace_id}              ← for agents
           ws:customer:{session_token}    ← for customers
    │
    └─ Each worker's subscriber picks up event
    │
    └─ Routes to active local WebSocket connections
```

Multi-worker safe: events reach customers/agents regardless of which server instance they're connected to.

---

## Token Tracking & Billing

Every LLM call is tracked at three levels:

```
Level 1: ai_agent_token_log (per call)
    - workspace_id, conversation_id, agent_id
    - call_type: "response_generation" | "tool_selection" |
                 "escalation_check" | "rag_rewrite" | "rag_response"
    - model, input_tokens, output_tokens, total_cost_usd
    - tool_name, tool_latency_ms, tool_success (for tool calls)

Level 2: ai_agent_conversations (per session aggregate)
    - total_input_tokens += input_tokens
    - total_output_tokens += output_tokens

Level 3: usage_counters (workspace quota)
    - Checked against tier monthly message limit
    - Blocks new messages when quota exceeded
```

**Cost estimation per 1000 tokens:**

| Model | Input | Output |
|-------|-------|--------|
| `claude-haiku-4-5` | $0.00025 | $0.00125 |
| `gpt-4o-mini` | $0.00015 | $0.00060 |
| `gemini-2.0-flash` | $0.000075 | $0.00030 |
| `llama-3.3-70b-versatile` | $0.00059 | $0.00079 |

**LLM calls per message (worst case — RAG with history + escalation check):**

| Call | Logged As |
|------|-----------|
| Query rewriting | `rag_rewrite` |
| Embedding generation | (not token-logged, separate cost) |
| Escalation classification | `escalation_check` |
| RAG response generation | `rag_response` |
| AI agent tool selection | `tool_selection` |
| AI agent response | `response_generation` |

---

## Business Hours Handling

**Triggered in Phase 1 if workspace has business hours configured.**

```
Check: is current time within workspace business hours?
    │
    ├─ INSIDE hours → continue normally
    │
    └─ OUTSIDE hours:
           │
           ├─ outside_hours_behavior == "inform_and_pause":
           │      ├─ Send outside_hours_message to customer
           │      ├─ Set conversation.status = "paused"
           │      └─ HALT — no further processing
           │
           └─ outside_hours_behavior == "inform_and_continue":
                  ├─ Send outside_hours_message to customer (informational)
                  └─ CONTINUE to routing phase normally
```

---

## Maintenance Mode

**Triggered in Phase 1.**

```
PlatformSetting "maintenance_mode" == "true"
    │
    └─ Return maintenance message to customer
       NO message stored in DB
       NO escalation triggered
       NO webhooks fired
```

---

## Contact Blocking

**Triggered in Phase 1.**

```
contact.is_blocked == True
    │
    └─ NO response sent to customer
       Customer message IS stored in DB (for audit trail)
       NO escalation triggered
       NO webhooks fired
       NO AI processing
```

Blocking is silent — the customer receives no indication they are blocked.

---

## Complete Decision Tree (All Scenarios Combined)

```
Message arrives at POST /api/webchat/send
│
├─ Maintenance mode? YES → return maintenance message (stop)
│
├─ Invalid widget? YES → 404 (stop)
│
├─ Rate limited? YES → 429 (stop)
│
├─ Duplicate message? YES → return existing silently (stop)
│
├─ Quota exceeded? YES → return quota error (stop)
│
├─ Contact blocked? YES → store message, return nothing (stop)
│
├─ Outside business hours?
│      ├─ "inform_and_pause" → send message, pause conversation (stop)
│      └─ "inform_and_continue" → send message, continue ↓
│
├─ Store customer message (ALWAYS)
│
├─ Fire webhooks: conversation.created, message.received (ALWAYS, async)
│
├─ ai_enabled == False
│      ├─ agents_enabled == True  → SCENARIO B (Direct Routing → Escalation)
│      └─ agents_enabled == False → SCENARIO A (Silent, nothing returned)
│
└─ ai_enabled == True
       ├─ ai_mode == "ai_agent"
       │      └─ SCENARIO C: AIAgentRunner.run()
       │             ├─ Agent not found/inactive → fall to SCENARIO D
       │             ├─ max_turns exceeded → ESCALATION PROCESSING
       │             ├─ LLM returns ESCALATE: → ESCALATION PROCESSING
       │             └─ Normal → create assistant message + notify customer
       │
       └─ ai_mode == "rag" (or AI agent fell through)
              │
              ├─ auto_escalation_enabled == True
              │      └─ EscalationClassifier.classify_message()
              │             ├─ Keyword OR LLM says escalate → ESCALATION PROCESSING
              │             └─ Not escalated → RAG PIPELINE ↓
              │
              └─ auto_escalation_enabled == False → RAG PIPELINE (no escalation check)
                     │
                     └─ RAGEngine.process_rag_query()
                            ├─ Small-talk → LLM direct answer
                            ├─ Has results → RAG response + notify customer
                            └─ No results (used_fallback)
                                   ├─ auto_escalation_enabled → ESCALATION PROCESSING
                                   └─ not enabled → return fallback_msg

ESCALATION PROCESSING (any path that escalates):
    ├─ Update conversation.status = "escalated"
    ├─ agents_enabled == True → assign agent, send acknowledgment, notify agents
    └─ agents_enabled == False → send acknowledgment, email owner (if enabled)
```

---

## Database State Changes Per Scenario

| Scenario | Message Rows Created | Conversation Status | Notes |
|----------|---------------------|--------------------|----|
| Maintenance | 0 | unchanged | Nothing stored |
| Duplicate | 0 | unchanged | Return existing |
| Blocked | 1 (customer) | unchanged | No reply stored |
| Outside hours (pause) | 2 (customer + system) | "paused" | No AI call |
| Outside hours (continue) | 2+ (customer + replies) | normal flow | AI runs normally |
| Scenario A | 1 (customer) | "active" | No reply |
| Scenario B | 3 (customer + system + assistant ack) | "escalated" or "agent" | Agent assigned |
| Scenario C (normal) | 2 (customer + assistant) | "active" | turn_count++ |
| Scenario C (escalated) | 3 (customer + system + assistant ack) | "escalated" | AI escalated |
| Scenario D (RAG success) | 2 (customer + assistant) | "active" | rag_used=true in metadata |
| Scenario D (RAG fallback, escalate) | 3 (customer + system + assistant ack) | "escalated" | RAG had no knowledge |
| Scenario D (RAG fallback, no escalate) | 2 (customer + fallback assistant) | "active" | workspace.fallback_msg used |
| Scenario D (escalated by classifier) | 3 (customer + system + assistant ack) | "escalated" | Keyword/LLM escalation |

---

## Feature Flag Matrix

Quick reference for every combination of key flags:

| `ai_enabled` | `ai_mode` | `agents_enabled` | `auto_escalation_enabled` | Behavior |
|---|---|---|---|---|
| `False` | any | `False` | any | Silent inbox — no response |
| `False` | any | `True` | any | Immediate escalation to human |
| `True` | `"rag"` | `False` | `False` | Pure RAG — no escalation ever, fallback message if no results |
| `True` | `"rag"` | `False` | `True` | RAG + escalation classifier; RAG fallback goes to "no agents" ack + email |
| `True` | `"rag"` | `True` | `False` | Pure RAG — escalation only if explicitly requested via agent reassignment |
| `True` | `"rag"` | `True` | `True` | Full flow — RAG with auto-escalation to human agents |
| `True` | `"ai_agent"` | `False` | `False` | AI agent with tools, no escalation path |
| `True` | `"ai_agent"` | `False` | `True` | AI agent + classifier; escalation goes to "no agents" ack + email |
| `True` | `"ai_agent"` | `True` | `False` | AI agent with tools; can self-escalate via `ESCALATE:` prefix or max_turns |
| `True` | `"ai_agent"` | `True` | `True` | Full AI agent + auto-escalation + human handoff |

---

*Last updated: 2026-05-07*
