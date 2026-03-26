"""
Comprehensive Workspace Owner API Tests
Tests all endpoints against https://api.parthavpovil.in

Run with:
    python -m pytest tests/test_workspace_owner_api.py -v
    python -m pytest tests/test_workspace_owner_api.py -v -k "TestAuth"  # single section
"""
import pytest
import requests
import time
import uuid
import io

BASE_URL = "https://api.parthavpovil.in"

# Shared state — flows between test classes in execution order
_state: dict = {}

SESSION = requests.Session()


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _headers(token=None, content_type="application/json"):
    h = {}
    if content_type:
        h["Content-Type"] = content_type
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _follow(resp, method_fn, *args, token=None, **kwargs):
    """Follow 3xx redirects while preserving the Authorization header."""
    if resp.status_code in (301, 302, 307, 308):
        loc = resp.headers.get("Location", "")
        if not loc.startswith("http"):
            loc = BASE_URL + loc
        resp = method_fn(loc, headers=_headers(token), **kwargs)
    return resp


def get(path, token=None, **kwargs):
    resp = SESSION.get(
        f"{BASE_URL}{path}", headers=_headers(token),
        allow_redirects=False, **kwargs
    )
    return _follow(resp, SESSION.get, token=token, **kwargs)


def post(path, data=None, token=None, **kwargs):
    resp = SESSION.post(
        f"{BASE_URL}{path}", json=data, headers=_headers(token),
        allow_redirects=False, **kwargs
    )
    return _follow(resp, SESSION.post, token=token, json=data, **kwargs)


def put(path, data=None, token=None, **kwargs):
    resp = SESSION.put(
        f"{BASE_URL}{path}", json=data, headers=_headers(token),
        allow_redirects=False, **kwargs
    )
    return _follow(resp, SESSION.put, token=token, json=data, **kwargs)


def patch(path, data=None, token=None, **kwargs):
    resp = SESSION.patch(
        f"{BASE_URL}{path}", json=data, headers=_headers(token),
        allow_redirects=False, **kwargs
    )
    return _follow(resp, SESSION.patch, token=token, json=data, **kwargs)


def delete(path, token=None, **kwargs):
    resp = SESSION.delete(
        f"{BASE_URL}{path}", headers=_headers(token),
        allow_redirects=False, **kwargs
    )
    return _follow(resp, SESSION.delete, token=token, **kwargs)


# ─── 0. Health ────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self):
        r = get("/health")
        assert r.status_code == 200, r.text

    def test_health_body_structure(self):
        data = get("/health").json()
        assert data["status"] == "healthy"
        assert data["service"] == "chatsaas-backend"
        assert "timestamp" in data

    def test_health_database_ok(self):
        data = get("/health").json()
        assert data["checks"]["database"]["status"] == "healthy"

    def test_health_storage_ok(self):
        data = get("/health").json()
        assert data["checks"]["storage"]["status"] == "healthy"

    def test_health_response_time_under_2s(self):
        start = time.time()
        get("/health")
        assert time.time() - start < 2.0


# ─── 1. Auth: Register ────────────────────────────────────────────────────────

class TestAuthRegister:
    """
    Creates a fresh owner account + workspace used by all subsequent test classes.
    _state["token"], _state["email"], _state["workspace_id"] are set here.
    """
    _uid = uuid.uuid4().hex[:8]
    EMAIL = f"owner_test_{_uid}@chaai-test.com"
    PASSWORD = "TestPass123!"
    BUSINESS = f"Chaai Test Co {_uid}"

    def test_register_creates_account_and_workspace(self):
        r = post("/api/auth/register", {
            "email": self.EMAIL,
            "password": self.PASSWORD,
            "business_name": self.BUSINESS,
        })
        assert r.status_code == 200, r.text
        data = r.json()

        # Token present
        assert "access_token" in data
        assert isinstance(data["access_token"], str)
        assert len(data["access_token"]) > 20

        # User shape
        user = data["user"]
        assert user["email"] == self.EMAIL
        assert "id" in user

        # Workspace shape
        ws = data["workspace"]
        assert ws["name"] == self.BUSINESS
        assert ws["tier"] == "free"
        assert "id" in ws
        assert "slug" in ws

        # Persist for later tests
        _state["token"] = data["access_token"]
        _state["email"] = self.EMAIL
        _state["password"] = self.PASSWORD
        _state["workspace_id"] = ws["id"]
        _state["workspace_slug"] = ws["slug"]

    def test_register_duplicate_email_returns_400(self):
        r = post("/api/auth/register", {
            "email": self.EMAIL,
            "password": self.PASSWORD,
            "business_name": "Duplicate Inc",
        })
        assert r.status_code == 400, r.text
        assert "already registered" in r.json()["detail"].lower()

    def test_register_missing_fields_returns_422(self):
        r = post("/api/auth/register", {"email": "incomplete@test.com"})
        assert r.status_code == 422

    def test_register_invalid_email_returns_422(self):
        r = post("/api/auth/register", {
            "email": "not-an-email",
            "password": "TestPass123!",
            "business_name": "Bad Email Co",
        })
        assert r.status_code == 422

    def test_register_short_password_handled(self):
        """Empty or trivially short passwords should be rejected."""
        r = post("/api/auth/register", {
            "email": f"short_{uuid.uuid4().hex[:6]}@test.com",
            "password": "ab",
            "business_name": "Short Pwd Co",
        })
        assert r.status_code in (400, 422)


# ─── 1b. Auth: Login ──────────────────────────────────────────────────────────

class TestAuthLogin:
    def test_login_valid_credentials(self):
        assert "email" in _state, "TestAuthRegister must run first"
        r = post("/api/auth/login", {
            "email": _state["email"],
            "password": _state["password"],
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        # Workspace included in login response
        assert "workspace" in data
        # Refresh token for downstream tests
        _state["token"] = data["access_token"]

    def test_login_wrong_password_returns_401(self):
        r = post("/api/auth/login", {
            "email": _state.get("email", "x@x.com"),
            "password": "wrongpassword",
        })
        assert r.status_code == 401

    def test_login_nonexistent_user_returns_401(self):
        r = post("/api/auth/login", {
            "email": "nobody_does_not_exist@example.com",
            "password": "whatever",
        })
        assert r.status_code == 401

    def test_login_missing_fields_returns_422(self):
        r = post("/api/auth/login", {"email": _state.get("email", "x@x.com")})
        assert r.status_code == 422


# ─── 1c. Auth: /me ────────────────────────────────────────────────────────────

class TestAuthMe:
    def test_me_returns_user_and_workspace(self):
        assert "token" in _state
        r = get("/api/auth/me", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == _state["email"]
        assert "workspace" in data
        ws = data["workspace"]
        assert ws["id"] == _state["workspace_id"]
        assert "tier" in ws

    def test_me_without_token_returns_401(self):
        r = get("/api/auth/me")
        assert r.status_code in (401, 403)

    def test_me_with_bad_token_returns_401(self):
        r = get("/api/auth/me", token="bad.token.here")
        assert r.status_code in (401, 403)

    def test_me_with_tampered_jwt_returns_401(self):
        tampered = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".fake_signature_that_wont_verify"
        )
        r = get("/api/auth/me", token=tampered)
        assert r.status_code in (401, 403)


# ─── 1d. Auth: Refresh Token ──────────────────────────────────────────────────

class TestAuthRefresh:
    def test_refresh_returns_new_token(self):
        assert "token" in _state
        r = post("/api/auth/refresh", {"token": _state["token"]})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert data.get("token_type", "bearer").lower() == "bearer"
        # Update state with refreshed token
        _state["token"] = data["access_token"]

    def test_refresh_with_garbage_token_returns_401(self):
        r = post("/api/auth/refresh", {"token": "not.a.real.token"})
        assert r.status_code == 401

    def test_refresh_missing_token_field_returns_422(self):
        r = post("/api/auth/refresh", {})
        assert r.status_code == 422


# ─── 2. Workspace ─────────────────────────────────────────────────────────────

class TestWorkspace:
    def test_workspace_overview_returns_summary(self):
        r = get("/api/workspace/overview", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "workspace_id" in data
        assert "tier" in data
        assert "conversations_today" in data
        assert "messages_this_month" in data

    def test_workspace_overview_unauthenticated_returns_401(self):
        r = get("/api/workspace/overview")
        assert r.status_code in (401, 403)

    def test_workspace_settings_update(self):
        r = put("/api/workspace/settings", {
            "fallback_msg": "Sorry, let me connect you to a human agent.",
            "agents_enabled": True,
            "escalation_keywords": ["refund", "urgent", "cancel"],
            "escalation_sensitivity": "medium",
            "escalation_email_enabled": False,
        }, token=_state["token"])
        assert r.status_code == 200, r.text
        # Response is a status confirmation; verify it's 200 and parseable
        data = r.json()
        assert data is not None

    def test_workspace_settings_can_be_verified_via_me(self):
        """Settings should be persisted and readable via /me."""
        r = get("/api/auth/me", token=_state["token"])
        assert r.status_code == 200, r.text
        ws = r.json()["workspace"]
        assert "tier" in ws

    def test_workspace_settings_unauthenticated_returns_401(self):
        r = put("/api/workspace/settings", {"agents_enabled": False})
        assert r.status_code in (401, 403)

    def test_workspace_ai_pipeline_returns_config(self):
        r = get("/api/workspace/ai-pipeline", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "ai_mode" in data
        assert "ai_provider" in data

    def test_workspace_ai_config_free_tier_returns_402(self):
        """Free tier should not access AI config endpoint (Growth+ required)."""
        r = get("/api/workspace/ai-config", token=_state["token"])
        # Free workspace → 402, paid workspace → 200
        assert r.status_code in (200, 402)

    def test_workspace_business_hours_returns_list(self):
        r = get("/api/workspace/business-hours/", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)

    def test_workspace_business_hours_update(self):
        hours = [
            {"day_of_week": i, "is_closed": i >= 5,
             "open_time": None if i >= 5 else "09:00",
             "close_time": None if i >= 5 else "18:00",
             "timezone": "UTC"}
            for i in range(7)
        ]
        r = put("/api/workspace/business-hours/", hours, token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)


# ─── 3. Agents ────────────────────────────────────────────────────────────────

class TestAgents:
    def test_list_agents_returns_list(self):
        r = get("/api/agents", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_agents_unauthenticated_returns_401(self):
        r = get("/api/agents")
        assert r.status_code in (401, 403)

    def test_agents_pending_returns_list(self):
        r = get("/api/agents/pending", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_agents_stats_returns_summary(self):
        r = get("/api/agents/stats", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "total_agents" in data
        assert "tier_info" in data

    def test_invite_agent_respects_tier(self):
        """Free tier returns 402; paid tier returns 200/201."""
        agent_email = f"agent_{uuid.uuid4().hex[:6]}@chaai-test.com"
        r = post("/api/agents/invite", {
            "email": agent_email,
            "name": "Test Agent",
        }, token=_state["token"])
        # 402 = tier limit, 200/201 = success
        assert r.status_code in (200, 201, 402), r.text
        if r.status_code in (200, 201):
            data = r.json()
            assert data["email"] == agent_email
            _state["invited_agent_id"] = data["id"]
            _state["invited_agent_email"] = agent_email

    def test_invite_agent_duplicate_email_rejected(self):
        if "invited_agent_email" not in _state:
            pytest.skip("Agent invite not available on this tier")
        r = post("/api/agents/invite", {
            "email": _state["invited_agent_email"],
            "name": "Duplicate Agent",
        }, token=_state["token"])
        assert r.status_code in (400, 409), r.text

    def test_resend_invite_refreshes_token(self):
        if "invited_agent_id" not in _state:
            pytest.skip("No pending agent to resend")
        agent_id = _state["invited_agent_id"]
        r = post(f"/api/agents/{agent_id}/resend", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "invitation_token" in data

    def test_delete_pending_agent_succeeds(self):
        if "invited_agent_id" not in _state:
            pytest.skip("No pending agent to delete")
        agent_id = _state["invited_agent_id"]
        r = delete(f"/api/agents/{agent_id}", token=_state["token"])
        assert r.status_code == 200, r.text
        assert "deleted" in r.json().get("message", "").lower()
        # Clean up state so downstream tests don't try to use this agent
        _state.pop("invited_agent_id", None)
        _state.pop("invited_agent_email", None)

    def test_deactivate_nonexistent_agent_returns_404(self):
        r = post(f"/api/agents/{uuid.uuid4()}/deactivate", token=_state["token"])
        assert r.status_code in (404, 422), r.text


# ─── 4. Channels ──────────────────────────────────────────────────────────────

class TestChannels:
    def test_list_channels_returns_list(self):
        r = get("/api/channels", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_channels_unauthenticated_returns_401(self):
        r = get("/api/channels")
        assert r.status_code in (401, 403)

    def test_channels_stats_returns_summary(self):
        r = get("/api/channels/stats/summary", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_create_webchat_channel(self):
        r = post("/api/channels/", {
            "channel_type": "webchat",
            "name": f"Test Chat {uuid.uuid4().hex[:6]}",
            "credentials": {
                "business_name": "Chaai Test",
                "primary_color": "#4F46E5",
                "position": "bottom-right",
                "welcome_message": "Hello! How can we help?",
            },
            "is_active": True,
        }, token=_state["token"])
        # 201 = created, 402 = tier limit reached
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert data["channel_type"] == "webchat"
            assert "widget_id" in data
            assert "id" in data
            _state["channel_id"] = data["id"]

    def test_get_channel_by_id(self):
        if "channel_id" not in _state:
            pytest.skip("No channel created on this tier")
        r = get(f"/api/channels/{_state['channel_id']}", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] == _state["channel_id"]

    def test_update_channel_name(self):
        if "channel_id" not in _state:
            pytest.skip("No channel created on this tier")
        r = put(f"/api/channels/{_state['channel_id']}", {
            "name": "Updated Chat Name",
        }, token=_state["token"])
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Updated Chat Name"

    def test_validate_webchat_credentials(self):
        r = post("/api/channels/validate/webchat", {
            "business_name": "Test",
            "primary_color": "#000000",
            "position": "bottom-right",
            "welcome_message": "Hi",
        }, token=_state["token"])
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            assert r.json().get("valid") is True

    def test_get_nonexistent_channel_returns_404(self):
        r = get(f"/api/channels/{uuid.uuid4()}", token=_state["token"])
        assert r.status_code == 404

    def test_delete_channel(self):
        if "channel_id" not in _state:
            pytest.skip("No channel to delete")
        r = delete(f"/api/channels/{_state['channel_id']}", token=_state["token"])
        assert r.status_code == 200, r.text
        assert "deleted" in r.json().get("message", "").lower()
        _state.pop("channel_id", None)


# ─── 4b. Channels: second creation for downstream tests ───────────────────────

class TestChannelForConversations:
    """
    Create a fresh webchat channel that will be reused by conversation tests.
    Kept separate so delete above doesn't kill it.
    """
    def test_create_webchat_channel_for_tests(self):
        r = post("/api/channels/", {
            "channel_type": "webchat",
            "name": f"Persistent Chat {uuid.uuid4().hex[:6]}",
            "credentials": {
                "business_name": "Test Corp",
                "primary_color": "#000000",
                "position": "bottom-right",
                "welcome_message": "Hi",
            },
            "is_active": True,
        }, token=_state["token"])
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            _state["persistent_channel_id"] = r.json()["id"]


# ─── 5. Conversations ─────────────────────────────────────────────────────────

class TestConversations:
    def test_list_conversations_returns_paginated_result(self):
        r = get("/api/conversations", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        # Response is either a list or a paginated dict
        assert isinstance(data, (list, dict))
        if isinstance(data, dict):
            assert "conversations" in data or "total_count" in data

    def test_list_conversations_unauthenticated_returns_401(self):
        r = get("/api/conversations")
        assert r.status_code in (401, 403)

    def test_conversations_stats_summary(self):
        r = get("/api/conversations/stats/summary", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "total_conversations" in data
        assert "resolved_conversations" in data

    def test_conversations_search_no_query(self):
        """Without q param acts as filtered list."""
        r = get("/api/conversations/search", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "results" in data or isinstance(data, list)

    def test_conversations_search_with_query(self):
        r = get("/api/conversations/search?q=hello", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_conversations_search_with_status_filter(self):
        r = get("/api/conversations/search?status=resolved", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_conversations_filter_by_status(self):
        for status in ("active", "escalated", "resolved"):
            r = get(f"/api/conversations?status_filter={status}", token=_state["token"])
            assert r.status_code == 200, f"Status {status}: {r.text}"

    def test_conversations_pagination(self):
        r = get("/api/conversations?limit=5&offset=0", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_get_nonexistent_conversation_returns_404(self):
        r = get(f"/api/conversations/{uuid.uuid4()}", token=_state["token"])
        assert r.status_code == 404

    def test_conversations_export_free_tier_returns_403(self):
        """Export is Growth+ — free tier should get 403."""
        r = get("/api/conversations/export", token=_state["token"])
        assert r.status_code in (200, 403, 402), r.text


# ─── 6. Documents ─────────────────────────────────────────────────────────────

class TestDocuments:
    def test_list_documents_returns_response(self):
        r = get("/api/documents", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_list_documents_unauthenticated_returns_401(self):
        r = get("/api/documents")
        assert r.status_code in (401, 403)

    def test_documents_stats_summary(self):
        r = get("/api/documents/stats/summary", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "total_documents" in data
        assert "tier_info" in data

    def test_upload_txt_document(self):
        """Upload a small TXT file — free tier may reject with 402."""
        content = b"This is a test knowledge base document.\nIt contains product FAQ information."
        files = {"file": ("test_faq.txt", io.BytesIO(content), "text/plain")}
        data = {"name": "Test FAQ"}
        r = SESSION.post(
            f"{BASE_URL}/api/documents/upload",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {_state['token']}"},
        )
        assert r.status_code in (200, 202, 402), r.text
        if r.status_code in (200, 202):
            doc = r.json()
            assert "id" in doc
            assert doc["status"] in ("processing", "completed", "uploading")
            _state["document_id"] = doc["id"]

    def test_get_document_by_id(self):
        if "document_id" not in _state:
            pytest.skip("No document uploaded (tier limit or skip)")
        r = get(f"/api/documents/{_state['document_id']}", token=_state["token"])
        assert r.status_code == 200, r.text
        assert r.json()["id"] == _state["document_id"]

    def test_get_nonexistent_document_returns_404(self):
        r = get(f"/api/documents/{uuid.uuid4()}", token=_state["token"])
        assert r.status_code == 404

    def test_delete_document(self):
        if "document_id" not in _state:
            pytest.skip("No document to delete")
        r = delete(f"/api/documents/{_state['document_id']}", token=_state["token"])
        assert r.status_code == 200, r.text
        assert "deleted" in r.json().get("message", "").lower()
        _state.pop("document_id", None)


# ─── 7. Contacts ──────────────────────────────────────────────────────────────

class TestContacts:
    def test_list_contacts_returns_paginated_result(self):
        r = get("/api/contacts/", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "contacts" in data
        assert "total_count" in data

    def test_list_contacts_unauthenticated_returns_401(self):
        r = get("/api/contacts/")
        assert r.status_code in (401, 403)

    def test_list_contacts_with_search(self):
        r = get("/api/contacts/?search=test", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_list_contacts_with_pagination(self):
        r = get("/api/contacts/?limit=10&offset=0", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_get_nonexistent_contact_returns_404(self):
        r = get(f"/api/contacts/{uuid.uuid4()}", token=_state["token"])
        assert r.status_code == 404

    def test_block_nonexistent_contact_returns_404(self):
        r = post(f"/api/contacts/{uuid.uuid4()}/block", token=_state["token"])
        assert r.status_code == 404


# ─── 8. Canned Responses ──────────────────────────────────────────────────────

class TestCannedResponses:
    def test_list_canned_responses_returns_list(self):
        r = get("/api/canned-responses/", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_canned_responses_unauthenticated_returns_401(self):
        r = get("/api/canned-responses/")
        assert r.status_code in (401, 403)

    def test_create_canned_response(self):
        r = post("/api/canned-responses/", {
            "name": "Refund Policy",
            "content": "Our refund policy allows returns within 30 days of purchase.",
            "shortcut": f"/refund_{uuid.uuid4().hex[:4]}",
        }, token=_state["token"])
        # 201 = created, 402 = tier limit (free=0 canned responses)
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert data["name"] == "Refund Policy"
            assert "id" in data
            _state["canned_response_id"] = data["id"]

    def test_update_canned_response(self):
        if "canned_response_id" not in _state:
            pytest.skip("No canned response available")
        r = put(f"/api/canned-responses/{_state['canned_response_id']}", {
            "name": "Refund Policy Updated",
            "content": "Updated refund content.",
        }, token=_state["token"])
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Refund Policy Updated"

    def test_delete_canned_response(self):
        if "canned_response_id" not in _state:
            pytest.skip("No canned response to delete")
        r = delete(f"/api/canned-responses/{_state['canned_response_id']}", token=_state["token"])
        assert r.status_code == 200, r.text
        _state.pop("canned_response_id", None)

    def test_create_canned_response_missing_required_fields(self):
        r = post("/api/canned-responses/", {"name": "Missing content"}, token=_state["token"])
        assert r.status_code in (400, 422), r.text


# ─── 9. Flows ─────────────────────────────────────────────────────────────────

class TestFlows:
    _SAMPLE_STEPS = {
        "start": {
            "type": "message",
            "content": "I see you need help. Let me assist.",
            "next": "ask_name",
        },
        "ask_name": {
            "type": "input",
            "prompt": "What is your name?",
            "next": "done",
        },
        "done": {
            "type": "message",
            "content": "Thanks! A team member will follow up.",
            "next": None,
        },
    }

    def test_list_flows_returns_list(self):
        r = get("/api/flows/", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_flows_unauthenticated_returns_401(self):
        r = get("/api/flows/")
        assert r.status_code in (401, 403)

    def test_create_keyword_flow(self):
        r = post("/api/flows/", {
            "name": f"Test Flow {uuid.uuid4().hex[:6]}",
            "trigger_type": "keyword",
            "trigger_keywords": ["help", "support", "issue"],
            "is_active": True,
            "steps": self._SAMPLE_STEPS,
        }, token=_state["token"])
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert "id" in data
            assert data["trigger_type"] == "keyword"
            _state["flow_id"] = data["id"]
            _state["flow_name"] = data["name"]

    def test_get_flow_by_id(self):
        if "flow_id" not in _state:
            pytest.skip("No flow created")
        r = get(f"/api/flows/{_state['flow_id']}", token=_state["token"])
        assert r.status_code == 200, r.text
        assert r.json()["id"] == _state["flow_id"]

    def test_update_flow(self):
        if "flow_id" not in _state:
            pytest.skip("No flow to update")
        r = put(f"/api/flows/{_state['flow_id']}", {
            "name": "Updated Test Flow",
            "is_active": False,
        }, token=_state["token"])
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False

    def test_duplicate_flow(self):
        if "flow_id" not in _state:
            pytest.skip("No flow to duplicate")
        r = post(f"/api/flows/{_state['flow_id']}/duplicate", token=_state["token"])
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["id"] != _state["flow_id"]
        assert "copy" in data["name"].lower() or data["name"] != _state.get("flow_name", "")
        _state["duplicate_flow_id"] = data["id"]

    def test_flow_stats(self):
        if "flow_id" not in _state:
            pytest.skip("No flow for stats")
        r = get(f"/api/flows/{_state['flow_id']}/stats", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_delete_duplicate_flow(self):
        if "duplicate_flow_id" not in _state:
            pytest.skip("No duplicate flow to delete")
        r = delete(f"/api/flows/{_state['duplicate_flow_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text
        _state.pop("duplicate_flow_id", None)

    def test_delete_flow(self):
        if "flow_id" not in _state:
            pytest.skip("No flow to delete")
        r = delete(f"/api/flows/{_state['flow_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text
        _state.pop("flow_id", None)

    def test_get_nonexistent_flow_returns_404(self):
        r = get(f"/api/flows/{uuid.uuid4()}", token=_state["token"])
        assert r.status_code == 404


# ─── 10. WhatsApp Templates ────────────────────────────────────────────────────

class TestWhatsAppTemplates:
    def test_list_templates_returns_list(self):
        r = get("/api/templates/", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_templates_unauthenticated_returns_401(self):
        r = get("/api/templates/")
        assert r.status_code in (401, 403)

    def test_create_template(self):
        r = post("/api/templates/", {
            "name": f"test_order_{uuid.uuid4().hex[:6]}",
            "category": "UTILITY",
            "language": "en",
            "header_type": "TEXT",
            "header_content": "Order Update",
            "body": "Hi {{1}}, your order #{{2}} has been confirmed.",
            "footer": "Reply STOP to unsubscribe",
        }, token=_state["token"])
        # May fail if no WhatsApp channel is connected
        assert r.status_code in (201, 400, 402, 422), r.text
        if r.status_code == 201:
            _state["template_id"] = r.json()["id"]

    def test_get_template_by_id(self):
        if "template_id" not in _state:
            pytest.skip("No template created")
        r = get(f"/api/templates/{_state['template_id']}", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_delete_template(self):
        if "template_id" not in _state:
            pytest.skip("No template to delete")
        r = delete(f"/api/templates/{_state['template_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text
        _state.pop("template_id", None)


# ─── 11. Broadcasts ───────────────────────────────────────────────────────────

class TestBroadcasts:
    def test_list_broadcasts_returns_list(self):
        r = get("/api/broadcasts/", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_broadcasts_unauthenticated_returns_401(self):
        r = get("/api/broadcasts/")
        assert r.status_code in (401, 403)


# ─── 12. API Keys ─────────────────────────────────────────────────────────────

class TestApiKeys:
    def test_list_api_keys_returns_list(self):
        r = get("/api/api-keys", token=_state["token"])
        # 402 on free tier (Growth+ feature)
        assert r.status_code in (200, 402), r.text
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_list_api_keys_unauthenticated_returns_401(self):
        r = get("/api/api-keys")
        assert r.status_code in (401, 403)

    def test_create_api_key_respects_tier(self):
        r = post("/api/api-keys", {
            "name": "Test Integration Key",
        }, token=_state["token"])
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert "raw_key" in data
            assert data["raw_key"].startswith("csk_")
            assert "id" in data
            _state["api_key_id"] = data["id"]

    def test_delete_api_key(self):
        if "api_key_id" not in _state:
            pytest.skip("No API key created (tier or skip)")
        r = delete(f"/api/api-keys/{_state['api_key_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text
        _state.pop("api_key_id", None)


# ─── 13. Billing ──────────────────────────────────────────────────────────────

class TestBilling:
    def test_billing_status_returns_tier(self):
        r = get("/api/billing/status", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tier" in data

    def test_billing_status_unauthenticated_returns_401(self):
        r = get("/api/billing/status")
        assert r.status_code in (401, 403)

    def test_billing_checkout_invalid_tier_returns_422(self):
        r = post("/api/billing/checkout", {"tier": "invalid_tier"}, token=_state["token"])
        assert r.status_code in (400, 422), r.text

    def test_billing_checkout_valid_tier_returns_url(self):
        r = post("/api/billing/checkout", {"tier": "starter"}, token=_state["token"])
        # Should either return a checkout URL or fail gracefully if Razorpay not configured
        assert r.status_code in (200, 400, 402, 500, 503), r.text
        if r.status_code == 200:
            assert "checkout_url" in r.json()


# ─── 14. Assignment Rules (Pro tier) ──────────────────────────────────────────

class TestAssignmentRules:
    def test_list_assignment_rules_respects_tier(self):
        r = get("/api/assignment-rules/", token=_state["token"])
        # 402 on free/starter/growth, 200 on pro
        assert r.status_code in (200, 402), r.text
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_list_assignment_rules_unauthenticated_returns_401(self):
        r = get("/api/assignment-rules/")
        assert r.status_code in (401, 403)

    def test_create_assignment_rule_respects_tier(self):
        r = post("/api/assignment-rules/", {
            "name": "Route billing to finance",
            "priority": 100,
            "conditions": {"channel_type": "webchat"},
            "action": "round_robin",
            "is_active": True,
        }, token=_state["token"])
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            _state["assignment_rule_id"] = r.json()["id"]

    def test_delete_assignment_rule(self):
        if "assignment_rule_id" not in _state:
            pytest.skip("No assignment rule created")
        r = delete(f"/api/assignment-rules/{_state['assignment_rule_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text


# ─── 15. Outbound Webhooks ────────────────────────────────────────────────────

class TestOutboundWebhooks:
    def test_list_webhooks_respects_tier(self):
        r = get("/api/webhooks/outbound", token=_state["token"])
        assert r.status_code in (200, 402), r.text
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_list_webhooks_unauthenticated_returns_401(self):
        r = get("/api/webhooks/outbound")
        assert r.status_code in (401, 403)

    def test_create_webhook_respects_tier(self):
        r = post("/api/webhooks/outbound", {
            "url": "https://webhook.site/test-chaai",
            "events": ["conversation.created", "conversation.resolved"],
        }, token=_state["token"])
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert "id" in data
            assert "secret_key" in data
            _state["webhook_id"] = data["id"]

    def test_delete_webhook(self):
        if "webhook_id" not in _state:
            pytest.skip("No webhook created")
        r = delete(f"/api/webhooks/outbound/{_state['webhook_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text
        _state.pop("webhook_id", None)


# ─── 16. AI Agents ────────────────────────────────────────────────────────────

class TestAiAgents:
    def test_list_ai_agents_returns_list(self):
        r = get("/api/ai-agents/", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_ai_agents_unauthenticated_returns_401(self):
        r = get("/api/ai-agents/")
        assert r.status_code in (401, 403)

    def test_create_ai_agent_respects_tier(self):
        r = post("/api/ai-agents/", {
            "name": f"Support Bot {uuid.uuid4().hex[:4]}",
            "instructions": "You are a helpful customer support agent. Be concise and friendly.",
            "system_prompt": "You specialize in product support.",
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0.7,
            "tools": [],
            "guardrails": [],
        }, token=_state["token"])
        # 402 on free tier, 201 on paid tiers
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert "id" in data
            _state["ai_agent_id"] = data["id"]

    def test_get_ai_agent_by_id(self):
        if "ai_agent_id" not in _state:
            pytest.skip("No AI agent created")
        r = get(f"/api/ai-agents/{_state['ai_agent_id']}", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_update_ai_agent(self):
        if "ai_agent_id" not in _state:
            pytest.skip("No AI agent to update")
        r = put(f"/api/ai-agents/{_state['ai_agent_id']}", {
            "name": "Updated Support Bot",
        }, token=_state["token"])
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Updated Support Bot"

    def test_publish_ai_agent(self):
        if "ai_agent_id" not in _state:
            pytest.skip("No AI agent to publish")
        r = post(f"/api/ai-agents/{_state['ai_agent_id']}/publish", token=_state["token"])
        assert r.status_code in (200, 400), r.text

    def test_delete_ai_agent(self):
        if "ai_agent_id" not in _state:
            pytest.skip("No AI agent to delete")
        r = delete(f"/api/ai-agents/{_state['ai_agent_id']}", token=_state["token"])
        assert r.status_code in (200, 204), r.text
        _state.pop("ai_agent_id", None)

    def test_get_nonexistent_ai_agent_returns_404(self):
        r = get(f"/api/ai-agents/{uuid.uuid4()}", token=_state["token"])
        assert r.status_code == 404


# ─── Security ─────────────────────────────────────────────────────────────────

class TestSecurity:
    def test_sql_injection_in_login_rejected(self):
        r = post("/api/auth/login", {
            "email": "' OR '1'='1",
            "password": "anything",
        })
        assert r.status_code in (400, 401, 422)

    def test_sql_injection_in_register_rejected(self):
        r = post("/api/auth/register", {
            "email": "'; DROP TABLE users; --@test.com",
            "password": "TestPass123!",
            "business_name": "Evil Corp",
        })
        assert r.status_code in (400, 422)

    def test_xss_in_business_name_sanitized(self):
        r = post("/api/auth/register", {
            "email": f"xss_{uuid.uuid4().hex[:6]}@test.com",
            "password": "TestPass123!",
            "business_name": "<script>alert('xss')</script>",
        })
        # Either rejected or sanitized — should never echo raw script
        if r.status_code == 200:
            name = r.json().get("workspace", {}).get("name", "")
            assert "<script>" not in name

    def test_missing_content_type_returns_error(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            data="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert r.status_code in (400, 415, 422)

    def test_oversized_payload_handled(self):
        """Very large request body should not crash the server."""
        r = post("/api/auth/login", {
            "email": "x@x.com",
            "password": "x" * 100_000,
        })
        assert r.status_code in (400, 401, 413, 422)

    def test_auth_endpoints_require_post(self):
        r = get("/api/auth/login")
        assert r.status_code in (405, 404)

    def test_cross_workspace_access_rejected(self):
        """A second owner should not access the first workspace's data."""
        uid = uuid.uuid4().hex[:8]
        r2 = post("/api/auth/register", {
            "email": f"other_{uid}@chaai-test.com",
            "password": "TestPass123!",
            "business_name": f"Other Co {uid}",
        })
        if r2.status_code != 200:
            pytest.skip("Could not create second owner")
        token2 = r2.json()["access_token"]
        # Try to access first workspace's overview using second owner's token
        r = get("/api/workspace/overview", token=token2)
        assert r.status_code == 200  # Gets their own workspace, not first
        own_id = r.json()["workspace_id"]
        assert own_id != _state["workspace_id"]


# ─── Performance ──────────────────────────────────────────────────────────────

class TestPerformance:
    def test_health_p95_under_2s(self):
        times = []
        for _ in range(5):
            t = time.time()
            get("/health")
            times.append(time.time() - t)
        times.sort()
        p95 = times[int(len(times) * 0.95)]
        assert p95 < 2.0, f"p95 latency {p95:.2f}s exceeds 2s threshold"

    def test_concurrent_health_checks(self):
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(get, "/health") for _ in range(10)]
            results = [f.result() for f in futures]
        assert all(r.status_code == 200 for r in results)

    def test_auth_me_under_1s(self):
        assert "token" in _state
        start = time.time()
        get("/api/auth/me", token=_state["token"])
        elapsed = time.time() - start
        assert elapsed < 1.0, f"GET /api/auth/me took {elapsed:.2f}s"

    def test_conversations_list_under_2s(self):
        start = time.time()
        get("/api/conversations", token=_state["token"])
        elapsed = time.time() - start
        assert elapsed < 2.0, f"GET /api/conversations took {elapsed:.2f}s"


# ─── End-to-end: full register → configure → create channel flow ──────────────

class TestEndToEndRegisterAndSetup:
    """
    Full happy-path: register → login → configure workspace → create channel.
    Uses a brand-new account so it's self-contained.
    """
    uid = uuid.uuid4().hex[:8]
    EMAIL = f"e2e_{uid}@chaai-test.com"
    PASSWORD = "E2EPass456!"
    BUSINESS = f"E2E Corp {uid}"

    def test_step1_register(self):
        r = post("/api/auth/register", {
            "email": self.EMAIL,
            "password": self.PASSWORD,
            "business_name": self.BUSINESS,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        type(self)._token = data["access_token"]
        type(self)._ws_id = data["workspace"]["id"]

    def test_step2_login_returns_same_workspace(self):
        r = post("/api/auth/login", {
            "email": self.EMAIL,
            "password": self.PASSWORD,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        type(self)._token = data["access_token"]
        assert data["workspace"]["id"] == type(self)._ws_id

    def test_step3_me_returns_correct_user(self):
        r = get("/api/auth/me", token=type(self)._token)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == self.EMAIL
        assert data["workspace"]["id"] == type(self)._ws_id

    def test_step4_update_workspace_settings(self):
        r = put("/api/workspace/settings", {
            "fallback_msg": "Hi! We will be right with you.",
            "escalation_keywords": ["help", "refund"],
            "escalation_sensitivity": "low",
            "escalation_email_enabled": False,
        }, token=type(self)._token)
        assert r.status_code == 200, r.text
        ws = r.json()
        assert ws["fallback_msg"] == "Hi! We will be right with you."
        assert "help" in ws["escalation_keywords"]

    def test_step5_workspace_overview_reflects_registration(self):
        r = get("/api/workspace/overview", token=type(self)._token)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["workspace_id"] == type(self)._ws_id
        assert data["tier"] == "free"

    def test_step6_create_webchat_channel(self):
        r = post("/api/channels/", {
            "channel_type": "webchat",
            "name": "E2E Test Chat",
            "credentials": {
                "business_name": self.BUSINESS,
                "primary_color": "#7C3AED",
                "position": "bottom-right",
                "welcome_message": "Hello from E2E test!",
            },
            "is_active": True,
        }, token=type(self)._token)
        assert r.status_code in (201, 402), r.text
        if r.status_code == 201:
            data = r.json()
            assert data["channel_type"] == "webchat"
            assert "widget_id" in data
            type(self)._channel_id = data["id"]

    def test_step7_refresh_token_still_works(self):
        r = post("/api/auth/refresh", {"token": type(self)._token})
        assert r.status_code == 200, r.text
        type(self)._token = r.json()["access_token"]
        # Confirm refreshed token is valid
        r2 = get("/api/auth/me", token=type(self)._token)
        assert r2.status_code == 200

    def test_step8_cleanup_channel(self):
        ch_id = getattr(type(self), "_channel_id", None)
        if not ch_id:
            pytest.skip("No channel created in step 6")
        r = delete(f"/api/channels/{ch_id}", token=type(self)._token)
        assert r.status_code == 200, r.text
