"""
Real End-to-End User Flow Tests — Deployed Backend
====================================================
Comprehensive coverage of all API endpoints.
Run against a live API server:

    BASE_URL=https://your-api.example.com pytest tests/test_user_flow.py -v

Flows covered (in order):
  Auth          : register, login, bad creds, me, refresh, unauth rejection
  Channels      : create webchat, list, get, update, stats
  Workspace     : overview, settings, ai-config (tier gate), ai-pipeline (tier gate)
  Canned resp.  : CRUD + free-tier limit
  Conversations : list empty, get, stats, search, notes, resolve
  WebChat       : send message, get messages, get config
  Contacts      : list, get, update, block, unblock
  Agents        : invite, accept, login, status, deactivate/reactivate, stats
  API Keys      : create, list, delete
  Assignment    : CRUD
  Business hrs  : get, update, outside-hours
  Flows         : CRUD, duplicate, stats
  Templates     : CRUD, preview
  Broadcasts    : create, list, get, update, cancel, stats
  Tier gates    : outbound webhooks, ai-agents (both require Growth+)
  Cleanup       : delete contact, delete channel, 404 confirm
"""

import os
import uuid
import pytest
import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

_RUN_ID = str(uuid.uuid4())[:8]
TEST_EMAIL     = f"flowtest_{_RUN_ID}@example.com"
TEST_PASSWORD  = "SecurePass123!"
TEST_BUSINESS  = f"Flow Test Co {_RUN_ID}"
AGENT_EMAIL    = f"agent_{_RUN_ID}@example.com"
AGENT_PASSWORD = "AgentPass456!"
AGENT_NAME     = f"Test Agent {_RUN_ID}"

_ctx: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=True)

def auth_headers() -> dict:
    return {"Authorization": f"Bearer {_ctx['token']}"}

def agent_headers() -> dict:
    return {"Authorization": f"Bearer {_ctx['agent_token']}"}


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 0 — Smoke check
# ═════════════════════════════════════════════════════════════════════════════

def test_00_server_is_reachable():
    with client() as c:
        r = c.get("/health")
    assert r.status_code == 200, (
        f"Server at {BASE_URL} returned {r.status_code}. "
        "Set BASE_URL env var to your deployed API."
    )


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Auth
# ═════════════════════════════════════════════════════════════════════════════

def test_01_register_new_user():
    with client() as c:
        r = c.post("/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "business_name": TEST_BUSINESS,
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    assert data["user"]["email"] == TEST_EMAIL
    assert data["workspace"]["name"] == TEST_BUSINESS
    assert data["workspace"]["tier"] == "free"
    _ctx["token"]        = data["access_token"]
    _ctx["user_id"]      = data["user"]["id"]
    _ctx["workspace_id"] = data["workspace"]["id"]


def test_02_duplicate_registration_rejected():
    with client() as c:
        r = c.post("/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": "AnotherPass123!",
            "business_name": "Dupe Co",
        })
    assert r.status_code == 400
    assert "already registered" in r.json()["detail"].lower()


def test_03_login():
    with client() as c:
        r = c.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
        })
    assert r.status_code == 200, r.text
    _ctx["token"] = r.json()["access_token"]


def test_04_bad_credentials_rejected():
    with client() as c:
        r = c.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": "WrongPassword",
        })
    assert r.status_code == 401


def test_05_get_me():
    with client() as c:
        r = c.get("/api/auth/me", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["email"] == TEST_EMAIL
    assert data["workspace"]["id"] == _ctx["workspace_id"]


def test_06_token_refresh():
    with client() as c:
        r = c.post("/api/auth/refresh", json={"token": _ctx["token"]})
    assert r.status_code == 200, r.text
    _ctx["token"] = r.json()["access_token"]


def test_07_unauthenticated_rejected():
    with client() as c:
        for path in ["/api/auth/me", "/api/channels/", "/api/conversations/"]:
            r = c.get(path)
            assert r.status_code in (401, 403), (
                f"Expected 401/403 for unauthenticated {path}, got {r.status_code}"
            )


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Channels
# ═════════════════════════════════════════════════════════════════════════════

def test_08_create_webchat_channel():
    with client() as c:
        r = c.post("/api/channels/", json={
            "channel_type": "webchat",
            "name": "My WebChat",
            "credentials": {
                "business_name": TEST_BUSINESS,
                "primary_color": "#4A90E2",
                "position": "bottom-right",
                "welcome_message": "Hello! How can we help you today?",
            },
            "is_active": True,
        }, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["channel_type"] == "webchat"
    assert data["is_active"] is True
    assert data.get("widget_id"), "WebChat channel must return a widget_id"
    _ctx["channel_id"] = data["id"]
    _ctx["widget_id"]  = data["widget_id"]


def test_09_list_channels():
    with client() as c:
        r = c.get("/api/channels/", headers=auth_headers())
    assert r.status_code == 200, r.text
    channels = r.json()
    assert isinstance(channels, list)
    assert _ctx["channel_id"] in [ch["id"] for ch in channels]


def test_10_get_channel_by_id():
    with client() as c:
        r = c.get(f"/api/channels/{_ctx['channel_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["id"] == _ctx["channel_id"]


def test_11a_deactivate_channel():
    with client() as c:
        r = c.put(f"/api/channels/{_ctx['channel_id']}",
                  json={"is_active": False}, headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_11b_reactivate_channel():
    with client() as c:
        r = c.put(f"/api/channels/{_ctx['channel_id']}",
                  json={"is_active": True}, headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True


def test_12_channel_stats():
    with client() as c:
        r = c.get("/api/channels/stats/summary", headers=auth_headers())
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["total_channels"] >= 1
    assert "tier_info" in stats


def test_12b_unknown_channel_returns_404():
    fake_id = str(uuid.uuid4())
    with client() as c:
        r = c.get(f"/api/channels/{fake_id}", headers=auth_headers())
    assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Workspace
# ═════════════════════════════════════════════════════════════════════════════

def test_13_workspace_overview():
    with client() as c:
        r = c.get("/api/workspace/overview", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["workspace_id"] == _ctx["workspace_id"]
    assert data["tier"] == "free"
    # Save slug for webchat config test
    _ctx["workspace_name"] = data["name"]


def test_14_update_workspace_settings():
    with client() as c:
        r = c.put("/api/workspace/settings", json={
            "fallback_msg": "We will get back to you shortly!",
            "alert_email": f"alerts_{_RUN_ID}@flowtest.com",
            "agents_enabled": True,
            "escalation_sensitivity": "high",
            "escalation_keywords": ["urgent", "help", "problem"],
        }, headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "updated"


def test_34_get_workspace_ai_config():
    with client() as c:
        r = c.get("/api/workspace/ai-config", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ai_provider" in data
    assert "has_api_key" in data


def test_35_update_ai_config_requires_growth_tier():
    """PUT /ai-config must return 403 on free tier."""
    with client() as c:
        r = c.put("/api/workspace/ai-config", json={
            "ai_provider": "openai",
            "ai_model": "gpt-4o",
        }, headers=auth_headers())
    assert r.status_code == 403, f"Expected 403 on free tier, got {r.status_code}: {r.text}"


def test_36_get_workspace_ai_pipeline():
    with client() as c:
        r = c.get("/api/workspace/ai-pipeline", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ai_mode" in data


def test_37_update_ai_pipeline_requires_growth_tier():
    """PUT /ai-pipeline must return 403 on free tier."""
    with client() as c:
        r = c.put("/api/workspace/ai-pipeline", json={
            "ai_mode": "rag",
        }, headers=auth_headers())
    assert r.status_code == 403, f"Expected 403 on free tier, got {r.status_code}: {r.text}"


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Canned Responses
# ═════════════════════════════════════════════════════════════════════════════

def test_15a_create_canned_response():
    with client() as c:
        r = c.post("/api/canned-responses", json={
            "name": "Greeting",
            "content": "Hello! Thanks for reaching out. How can we assist you today?",
            "shortcut": "/greet",
        }, headers=auth_headers())
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["name"] == "Greeting"
    _ctx["canned_id"] = data["id"]


def test_15b_fill_to_tier_limit():
    with client() as c:
        for i in range(2, 6):
            r = c.post("/api/canned-responses", json={
                "name": f"Response {i}",
                "content": f"Canned reply number {i}.",
            }, headers=auth_headers())
            assert r.status_code in (200, 201), f"Creating response {i} failed: {r.text}"


def test_15c_over_limit_returns_4xx():
    with client() as c:
        r = c.post("/api/canned-responses", json={
            "name": "Over Limit",
            "content": "This should be rejected.",
        }, headers=auth_headers())
    assert r.status_code in (402, 403), (
        f"Expected tier-limit rejection but got {r.status_code}: {r.text}"
    )


def test_16_list_canned_responses():
    with client() as c:
        r = c.get("/api/canned-responses", headers=auth_headers())
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 5
    assert _ctx["canned_id"] in [i["id"] for i in items]


def test_17_update_canned_response():
    with client() as c:
        r = c.put(f"/api/canned-responses/{_ctx['canned_id']}",
                  json={"name": "Welcome", "content": "Welcome! Let us know how we can help."},
                  headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Welcome"


def test_18_delete_canned_response():
    with client() as c:
        r = c.delete(f"/api/canned-responses/{_ctx['canned_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text
    with client() as c:
        items = c.get("/api/canned-responses", headers=auth_headers()).json()
    assert _ctx["canned_id"] not in [i["id"] for i in items]


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Conversations (empty workspace)
# ═════════════════════════════════════════════════════════════════════════════

def test_19_list_conversations_empty():
    with client() as c:
        r = c.get("/api/conversations/", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "conversations" in data
    assert isinstance(data["conversations"], list)
    assert data["total_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — WebChat (creates contact + conversation)
# ═════════════════════════════════════════════════════════════════════════════

def test_20_webchat_send_message():
    """Simulate a website visitor sending a message through the widget."""
    with client() as c:
        r = c.post("/api/webchat/send", json={
            "widget_id": _ctx["widget_id"],
            "message": "Hi there! I need help with my order.",
            "contact_name": "Test Customer",
            "contact_email": f"customer_{_RUN_ID}@example.com",
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert data["session_token"]
    assert data["message_id"]
    _ctx["session_token"] = data["session_token"]
    _ctx["webchat_message_id"] = data["message_id"]


def test_21_webchat_invalid_widget_returns_404():
    with client() as c:
        r = c.post("/api/webchat/send", json={
            "widget_id": "invalid-widget-id-000",
            "message": "Test",
        })
    assert r.status_code == 404


def test_22_webchat_get_messages():
    if "session_token" not in _ctx:
        pytest.skip("Skipping — webchat send message failed")
    with client() as c:
        r = c.get("/api/webchat/messages", params={
            "widget_id": _ctx["widget_id"],
            "session_token": _ctx["session_token"],
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "messages" in data
    assert isinstance(data["messages"], list)
    assert len(data["messages"]) >= 1
    assert data["session_token"] == _ctx["session_token"]
    # Save the user's message for later tests
    user_msgs = [m for m in data["messages"] if m["sender_type"] == "user"]
    if user_msgs:
        _ctx["user_message_id"] = user_msgs[0]["id"]


def test_23_webchat_continue_session():
    """Continuing the session appends to the same conversation."""
    if "session_token" not in _ctx:
        pytest.skip("Skipping — webchat send message failed")
    with client() as c:
        r = c.post("/api/webchat/send", json={
            "widget_id": _ctx["widget_id"],
            "session_token": _ctx["session_token"],
            "message": "Actually, I have a second question too.",
        })
    assert r.status_code == 200, r.text
    assert r.json()["session_token"] == _ctx["session_token"]


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Contacts
# ═════════════════════════════════════════════════════════════════════════════

def test_24_list_contacts():
    if "session_token" not in _ctx:
        pytest.skip("Skipping — webchat send message failed, no contacts created")
    with client() as c:
        r = c.get("/api/contacts/", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "contacts" in data
    assert data["total_count"] >= 1
    # Save the first contact for subsequent tests
    _ctx["contact_id"] = data["contacts"][0]["id"]


def test_25_get_contact_by_id():
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created")
    with client() as c:
        r = c.get(f"/api/contacts/{_ctx['contact_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == _ctx["contact_id"]
    assert "recent_conversations" in data


def test_26_search_contacts_by_name():
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created")
    with client() as c:
        r = c.get("/api/contacts/", params={"q": "Test Customer"}, headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["total_count"] >= 1


def test_27_update_contact():
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created")
    with client() as c:
        r = c.patch(f"/api/contacts/{_ctx['contact_id']}",
                    json={"name": "Updated Customer", "tags": ["vip", "test"]},
                    headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Updated Customer"
    assert "vip" in data["tags"]


def test_28_block_contact():
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created")
    with client() as c:
        r = c.post(f"/api/contacts/{_ctx['contact_id']}/block", headers=auth_headers())
    assert r.status_code == 200, r.text
    # Verify blocked
    with client() as c:
        contact = c.get(f"/api/contacts/{_ctx['contact_id']}", headers=auth_headers()).json()
    assert contact["is_blocked"] is True


def test_29_unblock_contact():
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created")
    with client() as c:
        r = c.post(f"/api/contacts/{_ctx['contact_id']}/unblock", headers=auth_headers())
    assert r.status_code == 200, r.text
    with client() as c:
        contact = c.get(f"/api/contacts/{_ctx['contact_id']}", headers=auth_headers()).json()
    assert contact["is_blocked"] is False


def test_30_filter_contacts_by_blocked():
    """Filter by is_blocked=false should return our unblocked contact."""
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created")
    with client() as c:
        r = c.get("/api/contacts/", params={"is_blocked": "false"}, headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["total_count"] >= 1


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Conversations (with data)
# ═════════════════════════════════════════════════════════════════════════════

def test_31_list_conversations_has_data():
    if "session_token" not in _ctx:
        pytest.skip("Skipping — webchat send message failed, no conversations created")
    with client() as c:
        r = c.get("/api/conversations/", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_count"] >= 1
    _ctx["conversation_id"] = data["conversations"][0]["id"]


def test_32_get_conversation_by_id():
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.get(f"/api/conversations/{_ctx['conversation_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == _ctx["conversation_id"]
    assert "messages" in data or "status" in data


def test_33_conversation_stats_summary():
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.get("/api/conversations/stats/summary", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total_conversations" in data
    assert data["total_conversations"] >= 1


def test_33b_search_conversations():
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.get("/api/conversations/search",
                  params={"q": "order"}, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "results" in data or "conversations" in data or isinstance(data, list)


def test_34_add_internal_note():
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.post(f"/api/conversations/{_ctx['conversation_id']}/notes",
                   json={"content": "Customer is asking about order #1234. Follow up needed."},
                   headers=auth_headers())
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["content"] == "Customer is asking about order #1234. Follow up needed."
    _ctx["note_id"] = data["id"]


def test_35_list_internal_notes():
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.get(f"/api/conversations/{_ctx['conversation_id']}/notes",
                  headers=auth_headers())
    assert r.status_code == 200, r.text
    notes = r.json()
    assert isinstance(notes, list)
    assert _ctx["note_id"] in [n["id"] for n in notes]


def test_36_get_csat_for_active_conversation():
    """Active conversations have no CSAT yet — endpoint should still return 200."""
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.get(f"/api/conversations/{_ctx['conversation_id']}/csat",
                  headers=auth_headers())
    assert r.status_code == 200, r.text


def test_37_resolve_conversation():
    if "conversation_id" not in _ctx:
        pytest.skip("Skipping — no conversation was created")
    with client() as c:
        r = c.post("/api/conversations/status", json={
            "conversation_id": _ctx["conversation_id"],
            "status": "resolved",
            "note": "Issue resolved by owner.",
        }, headers=auth_headers())
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — Agents
# ═════════════════════════════════════════════════════════════════════════════

def test_38_invite_agent():
    with client() as c:
        r = c.post("/api/agents/invite", json={
            "email": AGENT_EMAIL,
            "name": AGENT_NAME,
        }, headers=auth_headers())
    if r.status_code == 402:
        pytest.skip("Agent invite blocked by tier limit (free tier: 0 agents)")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == AGENT_EMAIL
    assert data["invitation_token"]
    _ctx["invitation_token"] = data["invitation_token"]
    _ctx["agent_record_id"]  = data["id"]


def test_39_list_pending_invitations():
    if "invitation_token" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.get("/api/agents/pending", headers=auth_headers())
    assert r.status_code == 200, r.text
    pending = r.json()
    assert isinstance(pending, list)
    assert any(p["email"] == AGENT_EMAIL for p in pending)


def test_40_get_invitation_by_token():
    if "invitation_token" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.get(f"/api/agents/invitation/{_ctx['invitation_token']}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == AGENT_EMAIL


def test_41_accept_invitation():
    """Agent creates their account via the invitation token."""
    if "invitation_token" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.post("/api/auth/accept-invite", json={
            "token": _ctx["invitation_token"],
            "password": AGENT_PASSWORD,
        })
    assert r.status_code == 200, r.text
    assert "created" in r.json()["message"].lower() or "success" in r.json().get("message", "").lower()


def test_42_agent_login():
    if "invitation_token" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.post("/api/auth/agent-login", json={
            "email": AGENT_EMAIL,
            "password": AGENT_PASSWORD,
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    _ctx["agent_token"] = data["access_token"]


def test_43_list_agents():
    if "agent_record_id" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.get("/api/agents/", headers=auth_headers())
    assert r.status_code == 200, r.text
    agents = r.json()
    assert isinstance(agents, list)
    assert any(a["email"] == AGENT_EMAIL for a in agents)


def test_44_agent_stats():
    if "agent_record_id" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.get("/api/agents/stats", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total_agents" in data
    assert data["total_agents"] >= 1


def test_45a_set_agent_status_online():
    if "agent_token" not in _ctx:
        pytest.skip("Skipping — agent login was blocked by tier limit")
    with client() as c:
        r = c.put("/api/agents/me/status", json={"status": "online"},
                  headers=agent_headers())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "online"


def test_45b_get_agent_status():
    if "agent_token" not in _ctx:
        pytest.skip("Skipping — agent login was blocked by tier limit")
    with client() as c:
        r = c.get("/api/agents/me/status", headers=agent_headers())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "online"


def test_46_deactivate_agent():
    if "agent_record_id" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.post(f"/api/agents/{_ctx['agent_record_id']}/deactivate",
                   headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_47_reactivate_agent():
    if "agent_record_id" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.post(f"/api/agents/{_ctx['agent_record_id']}/activate",
                   headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True


def test_47b_resend_invitation_after_accepted():
    """Resending an already-accepted invite should return an error."""
    if "agent_record_id" not in _ctx:
        pytest.skip("Skipping — agent invite was blocked by tier limit")
    with client() as c:
        r = c.post(f"/api/agents/{_ctx['agent_record_id']}/resend",
                   headers=auth_headers())
    # 400 since already accepted, or 200 if resend is allowed
    assert r.status_code in (200, 400), r.text


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 10 — API Keys
# ═════════════════════════════════════════════════════════════════════════════

def test_48_create_api_key():
    with client() as c:
        r = c.post("/api/api-keys", json={"name": "Test Key"},
                   headers=auth_headers())
    if r.status_code == 403:
        pytest.skip("API key creation blocked by tier limit (requires Growth+)")
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["name"] == "Test Key"
    assert "key" in data or "key_hash" in data or "prefix" in data
    _ctx["api_key_id"] = data["id"]


def test_49_list_api_keys():
    if "api_key_id" not in _ctx:
        pytest.skip("Skipping — API key creation was blocked by tier limit")
    with client() as c:
        r = c.get("/api/api-keys", headers=auth_headers())
    assert r.status_code == 200, r.text
    keys = r.json()
    assert isinstance(keys, list)
    assert any(k["id"] == _ctx["api_key_id"] for k in keys)


def test_50_delete_api_key():
    if "api_key_id" not in _ctx:
        pytest.skip("Skipping — API key creation was blocked by tier limit")
    with client() as c:
        r = c.delete(f"/api/api-keys/{_ctx['api_key_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text
    with client() as c:
        keys = c.get("/api/api-keys", headers=auth_headers()).json()
    assert not any(k["id"] == _ctx["api_key_id"] for k in keys)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 11 — Assignment Rules
# ═════════════════════════════════════════════════════════════════════════════

def test_51_create_assignment_rule():
    with client() as c:
        r = c.post("/api/assignment-rules", json={
            "name": "Round Robin Rule",
            "priority": 10,
            "conditions": {"channel_type": "webchat"},
            "action": "round_robin",
            "is_active": True,
        }, headers=auth_headers())
    if r.status_code == 403:
        pytest.skip("Assignment rules blocked by tier limit (requires Pro)")
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["name"] == "Round Robin Rule"
    _ctx["rule_id"] = data["id"]


def test_52_list_assignment_rules():
    if "rule_id" not in _ctx:
        pytest.skip("Skipping — assignment rule creation was blocked by tier limit")
    with client() as c:
        r = c.get("/api/assignment-rules", headers=auth_headers())
    assert r.status_code == 200, r.text
    rules = r.json()
    assert isinstance(rules, list)
    assert any(rule["id"] == _ctx["rule_id"] for rule in rules)


def test_53_update_assignment_rule():
    if "rule_id" not in _ctx:
        pytest.skip("Skipping — assignment rule creation was blocked by tier limit")
    with client() as c:
        r = c.put(f"/api/assignment-rules/{_ctx['rule_id']}",
                  json={"name": "Updated Rule", "priority": 20},
                  headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Updated Rule"


def test_54_delete_assignment_rule():
    if "rule_id" not in _ctx:
        pytest.skip("Skipping — assignment rule creation was blocked by tier limit")
    with client() as c:
        r = c.delete(f"/api/assignment-rules/{_ctx['rule_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text
    with client() as c:
        rules = c.get("/api/assignment-rules", headers=auth_headers()).json()
    assert not any(rule["id"] == _ctx["rule_id"] for rule in rules)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 12 — Business Hours
# ═════════════════════════════════════════════════════════════════════════════

def test_55_get_business_hours():
    with client() as c:
        r = c.get("/api/workspace/business-hours/", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_56_update_business_hours():
    schedule = [
        {"day_of_week": i, "is_closed": False, "open_time": "09:00", "close_time": "17:00", "timezone": "UTC"}
        for i in range(5)  # Mon–Fri open
    ] + [
        {"day_of_week": 5, "is_closed": True, "open_time": None, "close_time": None, "timezone": "UTC"},
        {"day_of_week": 6, "is_closed": True, "open_time": None, "close_time": None, "timezone": "UTC"},
    ]
    with client() as c:
        r = c.put("/api/workspace/business-hours/", json=schedule, headers=auth_headers())
    assert r.status_code == 200, r.text
    hours = r.json()
    assert isinstance(hours, list)


def test_57_update_outside_hours_settings():
    with client() as c:
        r = c.put("/api/workspace/business-hours/outside-hours-settings", json={
            "outside_hours_message": "We are currently closed. We'll respond when we open.",
            "outside_hours_behavior": "inform_and_continue",
        }, headers=auth_headers())
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 13 — Flows
# ═════════════════════════════════════════════════════════════════════════════

def test_58_create_flow():
    with client() as c:
        r = c.post("/api/flows", json={
            "name": "Onboarding Flow",
            "trigger_keywords": ["start", "begin", "help"],
            "trigger_type": "keyword",
            "is_active": True,
            "steps": {
                "start": {
                    "id": "start",
                    "type": "message",
                    "content": "Welcome! What can we help you with?",
                    "next": None,
                }
            },
        }, headers=auth_headers())
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["name"] == "Onboarding Flow"
    _ctx["flow_id"] = data["id"]


def test_59_list_flows():
    with client() as c:
        r = c.get("/api/flows", headers=auth_headers())
    assert r.status_code == 200, r.text
    flows = r.json()
    assert isinstance(flows, list)
    assert any(f["id"] == _ctx["flow_id"] for f in flows)


def test_60_get_flow_by_id():
    with client() as c:
        r = c.get(f"/api/flows/{_ctx['flow_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["id"] == _ctx["flow_id"]


def test_61_update_flow():
    with client() as c:
        r = c.put(f"/api/flows/{_ctx['flow_id']}",
                  json={"name": "Updated Onboarding Flow", "is_active": False},
                  headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Updated Onboarding Flow"
    assert data["is_active"] is False


def test_62_get_flow_stats():
    with client() as c:
        r = c.get(f"/api/flows/{_ctx['flow_id']}/stats", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total_started" in data
    assert "completion_rate" in data


def test_63_duplicate_flow():
    with client() as c:
        r = c.post(f"/api/flows/{_ctx['flow_id']}/duplicate", headers=auth_headers())
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert "(copy)" in data["name"]
    assert data["is_active"] is False
    _ctx["flow_copy_id"] = data["id"]


def test_64_delete_flow_copy():
    with client() as c:
        r = c.delete(f"/api/flows/{_ctx['flow_copy_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text


def test_64b_delete_flow():
    with client() as c:
        r = c.delete(f"/api/flows/{_ctx['flow_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text
    with client() as c:
        r = c.get(f"/api/flows/{_ctx['flow_id']}", headers=auth_headers())
    assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 14 — WhatsApp Templates
# ═════════════════════════════════════════════════════════════════════════════

def test_65_create_template():
    with client() as c:
        r = c.post("/api/templates", json={
            "name": f"test_template_{_RUN_ID}",
            "category": "UTILITY",
            "language": "en",
            "body": "Hello {{1}}, your order {{2}} is ready for pickup.",
            "footer": "Reply STOP to unsubscribe",
        }, headers=auth_headers())
    assert r.status_code in (200, 201, 403), r.text
    if r.status_code == 403:
        pytest.skip("Templates require a higher tier — skipping CRUD tests")
    _ctx["template_id"] = r.json()["id"]


def test_66_list_templates():
    if "template_id" not in _ctx:
        pytest.skip("Template not created (tier gate)")
    with client() as c:
        r = c.get("/api/templates", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_67_get_template_by_id():
    if "template_id" not in _ctx:
        pytest.skip("Template not created (tier gate)")
    with client() as c:
        r = c.get(f"/api/templates/{_ctx['template_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["id"] == _ctx["template_id"]


def test_68_update_template():
    if "template_id" not in _ctx:
        pytest.skip("Template not created (tier gate)")
    with client() as c:
        r = c.put(f"/api/templates/{_ctx['template_id']}",
                  json={"footer": "Updated footer"},
                  headers=auth_headers())
    assert r.status_code == 200, r.text


def test_69_preview_template():
    if "template_id" not in _ctx:
        pytest.skip("Template not created (tier gate)")
    with client() as c:
        r = c.get(f"/api/templates/{_ctx['template_id']}/preview", headers=auth_headers())
    assert r.status_code == 200, r.text


def test_70_delete_template():
    if "template_id" not in _ctx:
        pytest.skip("Template not created (tier gate)")
    with client() as c:
        r = c.delete(f"/api/templates/{_ctx['template_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 15 — Broadcasts
# ═════════════════════════════════════════════════════════════════════════════

def test_71_create_broadcast_requires_template():
    """Broadcasts require a template. Create a fresh one for this test."""
    # First create a template to use
    with client() as c:
        tr = c.post("/api/templates", json={
            "name": f"bcast_tpl_{_RUN_ID}",
            "category": "MARKETING",
            "language": "en",
            "body": "Special offer for {{1}}!",
        }, headers=auth_headers())

    if tr.status_code == 403:
        pytest.skip("Broadcasts/Templates require a higher tier")

    template_id = tr.json()["id"]
    _ctx["broadcast_template_id"] = template_id

    with client() as c:
        r = c.post("/api/broadcasts", json={
            "name": "Test Campaign",
            "template_id": template_id,
            "audience_type": "all",
            "variable_mapping": {},
        }, headers=auth_headers())
    assert r.status_code in (200, 201, 403), r.text
    if r.status_code == 403:
        pytest.skip("Broadcasts require a higher tier")
    data = r.json()
    assert data["name"] == "Test Campaign"
    _ctx["broadcast_id"] = data["id"]


def test_72_list_broadcasts():
    if "broadcast_id" not in _ctx:
        pytest.skip("Broadcast not created (tier gate)")
    with client() as c:
        r = c.get("/api/broadcasts", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_73_get_broadcast_by_id():
    if "broadcast_id" not in _ctx:
        pytest.skip("Broadcast not created (tier gate)")
    with client() as c:
        r = c.get(f"/api/broadcasts/{_ctx['broadcast_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["id"] == _ctx["broadcast_id"]


def test_74_update_broadcast():
    if "broadcast_id" not in _ctx:
        pytest.skip("Broadcast not created (tier gate)")
    with client() as c:
        r = c.put(f"/api/broadcasts/{_ctx['broadcast_id']}",
                  json={"name": "Renamed Campaign"},
                  headers=auth_headers())
    assert r.status_code == 200, r.text


def test_75_broadcast_stats():
    if "broadcast_id" not in _ctx:
        pytest.skip("Broadcast not created (tier gate)")
    with client() as c:
        r = c.get(f"/api/broadcasts/{_ctx['broadcast_id']}/stats", headers=auth_headers())
    assert r.status_code == 200, r.text


def test_76_broadcast_recipients():
    if "broadcast_id" not in _ctx:
        pytest.skip("Broadcast not created (tier gate)")
    with client() as c:
        r = c.get(f"/api/broadcasts/{_ctx['broadcast_id']}/recipients", headers=auth_headers())
    assert r.status_code == 200, r.text


def test_77_cancel_broadcast():
    if "broadcast_id" not in _ctx:
        pytest.skip("Broadcast not created (tier gate)")
    with client() as c:
        r = c.post(f"/api/broadcasts/{_ctx['broadcast_id']}/cancel", headers=auth_headers())
    assert r.status_code in (200, 400), r.text  # 400 if already in non-cancellable state


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 16 — Tier Gates
# ═════════════════════════════════════════════════════════════════════════════

def test_78_outbound_webhooks_require_growth_tier():
    """Creating an outbound webhook on free tier must return 403."""
    with client() as c:
        r = c.post("/api/webhooks/outbound", json={
            "url": "https://example.com/webhook",
            "events": ["conversation.created"],
        }, headers=auth_headers())
    assert r.status_code == 403, (
        f"Expected 403 on free tier for webhooks, got {r.status_code}: {r.text}"
    )


def test_79_ai_agents_require_starter_tier():
    """Creating an AI agent on free tier must return 403."""
    with client() as c:
        r = c.post("/api/ai-agents", json={
            "name": "Test AI Agent",
            "system_prompt": "You are a helpful assistant.",
        }, headers=auth_headers())
    assert r.status_code == 403, (
        f"Expected 403 on free tier for AI agents, got {r.status_code}: {r.text}"
    )


def test_80_list_ai_agents_returns_empty_on_free_tier():
    """Listing AI agents is allowed but should return empty on free tier."""
    with client() as c:
        r = c.get("/api/ai-agents", headers=auth_headers())
    # Either 200 with empty list or 403
    assert r.status_code in (200, 403), r.text
    if r.status_code == 200:
        assert isinstance(r.json(), list)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 17 — Cleanup
# ═════════════════════════════════════════════════════════════════════════════

def test_81_delete_contact():
    if "contact_id" not in _ctx:
        pytest.skip("Skipping — no contact was created (webchat message failed)")
    with client() as c:
        r = c.delete(f"/api/contacts/{_ctx['contact_id']}", headers=auth_headers())
    assert r.status_code in (200, 204), r.text
    with client() as c:
        r = c.get(f"/api/contacts/{_ctx['contact_id']}", headers=auth_headers())
    assert r.status_code == 404


def test_82_delete_channel():
    with client() as c:
        r = c.delete(f"/api/channels/{_ctx['channel_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Channel deleted successfully"
    with client() as c:
        channels = c.get("/api/channels/", headers=auth_headers()).json()
    assert _ctx["channel_id"] not in [ch["id"] for ch in channels]


def test_83_deleted_channel_returns_404():
    with client() as c:
        r = c.get(f"/api/channels/{_ctx['channel_id']}", headers=auth_headers())
    assert r.status_code == 404
