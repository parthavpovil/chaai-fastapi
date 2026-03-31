# Frontend Implementation Plan — ChatSaaS Dashboard

> Authentication is **done**. This document defines the order of all remaining features to ship a professional, production-ready dashboard.

---

## Phase 1 — App Shell & Navigation
*Everything else depends on this being solid first.*

| # | Feature | Key Details |
|---|---------|-------------|
| 1.1 | **Layout Shell** | Sidebar nav, top bar, workspace switcher, user avatar/menu |
| 1.2 | **Route Guards** | Protect all routes, redirect unauthenticated users to login |
| 1.3 | **Token Refresh** | Intercept 401s, call `POST /api/auth/refresh`, retry request |
| 1.4 | **WebSocket Connection** | Establish persistent WS on app load, reconnect on drop |
| 1.5 | **Global Notification Toast** | Success / Error / Info toasts driven by WS events and API responses |

---

## Phase 2 — Dashboard Home (Overview)
*First screen after login — must feel polished.*

| # | Feature | Key Details |
|---|---------|-------------|
| 2.1 | **Workspace Overview** | `GET /api/workspace/overview` — total conversations, open, resolved, active agents |
| 2.2 | **Stats Cards** | Messages today, avg response time, CSAT score |
| 2.3 | **Recent Conversations** | Latest 10 conversations with status badges |

---

## Phase 3 — Conversation Inbox (Core Feature)
*This is the primary daily-use screen for agents.*

| # | Feature | Key Details |
|---|---------|-------------|
| 3.1 | **Conversation List** | `GET /api/conversations` — paginated, filterable by status/channel/agent |
| 3.2 | **Search Conversations** | `GET /api/conversations/search` — debounced search input |
| 3.3 | **Conversation Detail View** | Full message history, contact info panel on the right |
| 3.4 | **Send Message** | `POST /api/conversations/{id}/messages` — text input + send button |
| 3.5 | **Real-time Messages** | Receive new messages via WebSocket without page reload |
| 3.6 | **Claim Conversation** | `POST /api/conversations/claim` — agent takes ownership |
| 3.7 | **Update Status** | `POST /api/conversations/status` — resolve, escalate, reopen |
| 3.8 | **Internal Notes** | `POST/GET /api/conversations/{id}/notes` — hidden from customer |
| 3.9 | **AI Feedback** | Thumbs up/down on AI-generated messages |
| 3.10 | **My Active Conversations** | `GET /api/conversations/my/active` — agent's own queue tab |

---

## Phase 4 — Contact Management

| # | Feature | Key Details |
|---|---------|-------------|
| 4.1 | **Contacts List** | `GET /api/contacts` — paginated table with search |
| 4.2 | **Contact Detail Page** | Info, conversation history, block/unblock action |
| 4.3 | **Edit Contact** | `PATCH /api/contacts/{id}` — update name, metadata |
| 4.4 | **Block / Delete Contact** | Confirm modal before destructive actions |

---

## Phase 5 — Channel Setup
*Must be done early so the workspace can start receiving messages.*

| # | Feature | Key Details |
|---|---------|-------------|
| 5.1 | **Channels List Page** | `GET /api/channels` — show all connected channels with status |
| 5.2 | **Add Channel Flow** | Step-by-step wizard: select type → enter credentials → validate → save |
| 5.3 | **Validate Credentials** | `POST /api/channels/validate/{channel_type}` — show success/error inline |
| 5.4 | **Edit / Delete Channel** | `PUT` / `DELETE /api/channels/{id}` |
| 5.5 | **Channel Stats** | `GET /api/channels/stats/summary` — messages per channel |
| 5.6 | **WebChat Widget Config** | Show embed snippet with copy button after creating a WebChat channel |

---

## Phase 6 — Agent Management

| # | Feature | Key Details |
|---|---------|-------------|
| 6.1 | **Agents List** | `GET /api/agents` — table with status indicators (online/offline/busy) |
| 6.2 | **Invite Agent** | `POST /api/agents/invite` — email input form |
| 6.3 | **Pending Invites** | `GET /api/agents/pending` — resend / cancel pending invitations |
| 6.4 | **Activate / Deactivate** | Toggle agent access with confirm modal |
| 6.5 | **Agent Performance Stats** | `GET /api/agents/stats` — conversations handled, avg response time |
| 6.6 | **My Status Toggle** | Agent can set themselves online/offline/busy (`PUT /api/agents/me/status`) |

---

## Phase 7 — Knowledge Base (Documents)

| # | Feature | Key Details |
|---|---------|-------------|
| 7.1 | **Documents List** | `GET /api/documents` — table showing name, size, status, uploaded date |
| 7.2 | **Upload Document** | `POST /api/documents/upload` — drag-and-drop for PDF/TXT with progress bar |
| 7.3 | **Reprocess Document** | `POST /api/documents/{id}/reprocess` — re-generate embeddings |
| 7.4 | **Delete Document** | Confirm modal before delete |
| 7.5 | **Document Stats** | `GET /api/documents/stats/summary` — storage used, chunk count |

---

## Phase 8 — AI Configuration

| # | Feature | Key Details |
|---|---------|-------------|
| 8.1 | **AI Provider Config** | `GET/PUT /api/workspace/ai-config` — select provider (Gemini/OpenAI/Groq), enter API key, set model |
| 8.2 | **AI Pipeline Config** | `GET/PUT /api/workspace/ai-pipeline` — toggle RAG, escalation, response style |
| 8.3 | **AI Agents List** | `GET /api/ai-agents` — list configured bots |
| 8.4 | **Create / Edit AI Agent** | Name, system prompt, model, temperature, tone |
| 8.5 | **AI Agent Tools** | Add HTTP tools with parameter schema; test tool execution inline |
| 8.6 | **AI Agent Guardrails** | Add forbidden topic rules; show active guardrails list |
| 8.7 | **Assign Agent to Channel** | Link AI agent to one or more channels |
| 8.8 | **Sandbox / Test Agent** | Chat interface to test agent before publishing |
| 8.9 | **Publish Agent** | `POST /api/ai-agents/{id}/publish` — promote draft to live |
| 8.10 | **AI Agent Analytics** | `GET /api/ai-agents/{id}/analytics` — token usage, escalation rate |

---

## Phase 9 — Canned Responses

| # | Feature | Key Details |
|---|---------|-------------|
| 9.1 | **Canned Responses List** | `GET /api/canned-responses` — searchable by keyword |
| 9.2 | **Create / Edit Response** | Title + body text, shortcut key (optional) |
| 9.3 | **Insert in Chat** | In conversation view, `/` to open quick picker |
| 9.4 | **Delete Response** | Confirm before delete |

---

## Phase 10 — Business Hours

| # | Feature | Key Details |
|---|---------|-------------|
| 10.1 | **Business Hours Config** | `GET/PUT /api/business-hours` — day-by-day open/close times |
| 10.2 | **Outside Hours Settings** | `PUT /api/business-hours/outside-hours-settings` — auto-reply message, fallback behavior |

---

## Phase 11 — Assignment Rules

| # | Feature | Key Details |
|---|---------|-------------|
| 11.1 | **Rules List** | `GET /api/assignment-rules` — table of active rules |
| 11.2 | **Create / Edit Rule** | Condition builder (channel is X, keyword contains Y) → assign to agent |
| 11.3 | **Delete Rule** | With confirm |

---

## Phase 12 — WhatsApp Templates

| # | Feature | Key Details |
|---|---------|-------------|
| 12.1 | **Templates List** | `GET /api/templates` — status badges (pending, approved, rejected) |
| 12.2 | **Create Template** | Header, body, footer, button config; preview pane on right |
| 12.3 | **Preview Template** | `GET /api/templates/{id}/preview` |
| 12.4 | **Submit for Approval** | `POST /api/templates/{id}/submit` |
| 12.5 | **Edit / Delete Template** | Only allowed before approval |

---

## Phase 13 — Broadcasts

| # | Feature | Key Details |
|---|---------|-------------|
| 13.1 | **Broadcasts List** | `GET /api/broadcasts` — status: draft, scheduled, sent, cancelled |
| 13.2 | **Create Broadcast** | Select template → pick recipients (contacts/tags/channel) → schedule |
| 13.3 | **Send / Cancel** | `POST /api/broadcasts/{id}/send` or `/cancel` |
| 13.4 | **Broadcast Stats** | Sent, delivered, failed counts per broadcast |
| 13.5 | **Recipients List** | Per-contact delivery status with pagination |

---

## Phase 14 — Flow Builder

| # | Feature | Key Details |
|---|---------|-------------|
| 14.1 | **Flows List** | `GET /api/flows` — cards with last-edited date |
| 14.2 | **Create / Duplicate Flow** | Name + description form; clone existing |
| 14.3 | **Flow Editor** | Visual node-based builder (use `React Flow` or `xyflow`) — steps, branches, message nodes |
| 14.4 | **Save Flow** | `PUT /api/flows/{id}` |
| 14.5 | **Flow Stats** | `GET /api/flows/{id}/stats` — engagements, completions, drop-off |
| 14.6 | **Delete Flow** | With confirm modal |

---

## Phase 15 — Outbound Webhooks

| # | Feature | Key Details |
|---|---------|-------------|
| 15.1 | **Webhooks List** | `GET /api/outbound-webhooks` |
| 15.2 | **Create / Edit Webhook** | URL, event triggers (new conversation, message, escalation), headers |
| 15.3 | **Delivery Logs** | `GET /api/outbound-webhooks/{id}/logs` — success/failure with response body |

---

## Phase 16 — API Keys

| # | Feature | Key Details |
|---|---------|-------------|
| 16.1 | **API Keys List** | `GET /api/api-keys` — masked key display |
| 16.2 | **Generate Key** | Name + create; show full key **once** in a modal |
| 16.3 | **Revoke Key** | Delete with confirm |

---

## Phase 17 — Billing & Subscription

| # | Feature | Key Details |
|---|---------|-------------|
| 17.1 | **Billing Status Page** | `GET /api/billing/status` — current tier, usage bar for messages/agents/storage |
| 17.2 | **Upgrade Plan Flow** | `POST /api/billing/checkout` — Razorpay payment integration |
| 17.3 | **Cancel Subscription** | `POST /api/billing/cancel` — confirm modal with warning |

---

## Phase 18 — Workspace Settings

| # | Feature | Key Details |
|---|---------|-------------|
| 18.1 | **General Settings** | `GET/PUT /api/workspace/settings` — name, logo, timezone, language |
| 18.2 | **Workspace Slug / Public Info** | Used for WebChat widget embedding |

---

## Phase 19 — Analytics & Reports

| # | Feature | Key Details |
|---|---------|-------------|
| 19.1 | **Conversation Analytics** | `GET /api/conversations/stats/summary` — volume by day/channel/agent |
| 19.2 | **Agent Performance** | `GET /api/agents/stats` — per-agent table with charts |
| 19.3 | **CSAT Reports** | `GET /api/metrics/csat` — score over time, per-channel |
| 19.4 | **AI Feedback Stats** | Thumbs up/down ratio per channel |
| 19.5 | **Export Conversations** | `GET /api/conversations/export` — download CSV |

---

## Phase 20 — Polish & Production Readiness

| # | Feature | Key Details |
|---|---------|-------------|
| 20.1 | **Empty States** | Helpful zero-state UI for every list page |
| 20.2 | **Loading Skeletons** | Replace spinners with skeleton screens on all data-heavy views |
| 20.3 | **Error Boundaries** | Graceful crash pages, retry buttons |
| 20.4 | **Responsive Layout** | Ensure inbox and settings work on smaller screens |
| 20.5 | **Keyboard Shortcuts** | `C` = new conversation, `R` = reply, `/` = canned responses, `Esc` = close |
| 20.6 | **Notification Badges** | Sidebar shows unread conversation counts in real-time via WS |
| 20.7 | **Confirmation Modals** | All destructive actions (delete, block, cancel, deactivate) must confirm |
| 20.8 | **Accessibility** | Focus management, ARIA labels on icon-only buttons |

---

## Agent-Specific Accept Invite Flow
*(Separate from workspace owner dashboard)*

| # | Feature | Key Details |
|---|---------|-------------|
| A.1 | **Invite Landing Page** | `GET /api/agents/invitation/{token}` — show workspace name, role |
| A.2 | **Set Password & Accept** | `POST /api/auth/accept-invite` — agent sets password |
| A.3 | **Agent Login** | `POST /api/api/agent-login` — separate login for agent role |

---

## Implementation Notes

- **API Base URL:** `http://localhost:8000` (dev) — use env variable
- **Auth:** JWT bearer token in `Authorization` header; store in memory (not localStorage) for security
- **WebSocket:** Connect to WS endpoint on login; all real-time inbox updates come through here
- **Pagination:** All list endpoints are paginated — implement infinite scroll or page controls from day one
- **Role awareness:** Workspace Owner sees all settings pages; Agents only see Inbox, Contacts, and their own status
- **Tier gating:** Show upgrade prompts when `GET /api/billing/status` indicates limit reached

---

*Backend API docs: `backend/API_DOCUMENTATION.md`*  
*Postman collection: `backend/ChatSaaS_Backend_API.postman_collection.json`*
