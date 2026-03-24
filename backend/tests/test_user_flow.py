"""
Real End-to-End User Flow Tests — Deployed Backend
====================================================
Runs against a live API server. Set the base URL via:

    BASE_URL=https://your-api.example.com pytest tests/test_user_flow.py -v

Flows covered (in order):
  1.  Register account
  2.  Reject duplicate registration
  3.  Login
  4.  Reject bad credentials
  5.  GET /api/auth/me
  6.  Token refresh
  7.  Reject unauthenticated requests
  8.  Create WebChat channel
  9.  List channels
  10. Get channel by ID
  11. Update channel (deactivate / reactivate)
  12. Channel statistics
  13. Workspace overview
  14. Update workspace settings
  15. Create canned responses (and hit free-tier limit of 5)
  16. List canned responses
  17. Update canned response
  18. Delete canned response
  19. List conversations (empty workspace — checks shape)
  20. Delete channel
  21. Confirm deleted channel returns 404
"""

import os
import uuid
import pytest
import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# Unique suffix so the test can run multiple times without email conflicts
_RUN_ID = str(uuid.uuid4())[:8]
TEST_EMAIL = f"flowtest_{_RUN_ID}@example.com"
TEST_PASSWORD = "SecurePass123!"
TEST_BUSINESS = f"Flow Test Co {_RUN_ID}"

# Shared mutable state (populated as tests run in sequence)
_ctx: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def api(path: str) -> str:
    """Build full URL, ensuring no double-slash issues."""
    return f"{BASE_URL}/{path.lstrip('/')}"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30, follow_redirects=True)


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {_ctx['token']}"}


# ─────────────────────────────────────────────────────────────────────────────
# Smoke-check: server must be reachable
# ─────────────────────────────────────────────────────────────────────────────

def test_00_server_is_reachable():
    with client() as c:
        r = c.get("/health")
    assert r.status_code == 200, (
        f"Server at {BASE_URL} returned {r.status_code}. "
        "Set BASE_URL env var to your deployed API."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Flow 1 – Register
# ─────────────────────────────────────────────────────────────────────────────

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

    _ctx["token"] = data["access_token"]
    _ctx["user_id"] = data["user"]["id"]
    _ctx["workspace_id"] = data["workspace"]["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 2 – Duplicate registration rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_02_duplicate_registration_rejected():
    with client() as c:
        r = c.post("/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": "AnotherPass123!",
            "business_name": "Dupe Co",
        })
    assert r.status_code == 400
    assert "already registered" in r.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Flow 3 – Login
# ─────────────────────────────────────────────────────────────────────────────

def test_03_login():
    with client() as c:
        r = c.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
        })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    _ctx["token"] = data["access_token"]  # refresh to freshest token


# ─────────────────────────────────────────────────────────────────────────────
# Flow 4 – Bad credentials rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_04_bad_credentials_rejected():
    with client() as c:
        r = c.post("/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": "WrongPassword",
        })
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Flow 5 – GET /api/auth/me
# ─────────────────────────────────────────────────────────────────────────────

def test_05_get_me():
    with client() as c:
        r = c.get("/api/auth/me", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["email"] == TEST_EMAIL
    assert data["workspace"]["id"] == _ctx["workspace_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 6 – Token refresh
# ─────────────────────────────────────────────────────────────────────────────

def test_06_token_refresh():
    with client() as c:
        r = c.post("/api/auth/refresh", json={"token": _ctx["token"]})
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    assert new_token
    _ctx["token"] = new_token  # use fresh token going forward


# ─────────────────────────────────────────────────────────────────────────────
# Flow 7 – Unauthenticated requests rejected (401 or 403)
# ─────────────────────────────────────────────────────────────────────────────

def test_07_unauthenticated_rejected():
    """Protected endpoints must reject missing tokens with 401 or 403."""
    with client() as c:
        for path in ["/api/auth/me", "/api/channels/", "/api/conversations/"]:
            r = c.get(path)
            assert r.status_code in (401, 403), (
                f"Expected 401/403 for unauthenticated {path}, got {r.status_code}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Flow 8 – Create WebChat channel (no external API call needed)
# ─────────────────────────────────────────────────────────────────────────────

def test_08_create_webchat_channel():
    payload = {
        "channel_type": "webchat",
        "name": "My WebChat",
        "credentials": {
            "business_name": TEST_BUSINESS,
            "primary_color": "#4A90E2",
            "position": "bottom-right",
            "welcome_message": "Hello! How can we help you today?",
        },
        "is_active": True,
    }
    with client() as c:
        r = c.post("/api/channels/", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["channel_type"] == "webchat"
    assert data["is_active"] is True
    assert "id" in data
    assert data.get("widget_id"), "WebChat channel must return a widget_id"

    _ctx["channel_id"] = data["id"]
    _ctx["widget_id"] = data["widget_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 9 – List channels
# ─────────────────────────────────────────────────────────────────────────────

def test_09_list_channels():
    with client() as c:
        r = c.get("/api/channels/", headers=auth_headers())
    assert r.status_code == 200, r.text
    channels = r.json()
    assert isinstance(channels, list)
    assert len(channels) >= 1
    assert _ctx["channel_id"] in [ch["id"] for ch in channels]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 10 – Get channel by ID
# ─────────────────────────────────────────────────────────────────────────────

def test_10_get_channel_by_id():
    with client() as c:
        r = c.get(f"/api/channels/{_ctx['channel_id']}", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == _ctx["channel_id"]
    assert data["channel_type"] == "webchat"


# ─────────────────────────────────────────────────────────────────────────────
# Flow 11 – Update channel (deactivate → reactivate)
# ─────────────────────────────────────────────────────────────────────────────

def test_11a_deactivate_channel():
    with client() as c:
        r = c.put(
            f"/api/channels/{_ctx['channel_id']}",
            json={"is_active": False},
            headers=auth_headers(),
        )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_11b_reactivate_channel():
    with client() as c:
        r = c.put(
            f"/api/channels/{_ctx['channel_id']}",
            json={"is_active": True},
            headers=auth_headers(),
        )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Flow 12 – Channel statistics
# ─────────────────────────────────────────────────────────────────────────────

def test_12_channel_stats():
    with client() as c:
        r = c.get("/api/channels/stats/summary", headers=auth_headers())
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["total_channels"] >= 1
    assert stats["active_channels"] >= 1
    assert "tier_info" in stats
    assert stats["tier_info"]["current_tier"] == "free"


# ─────────────────────────────────────────────────────────────────────────────
# Flow 13 – Workspace overview
# ─────────────────────────────────────────────────────────────────────────────

def test_13_workspace_overview():
    with client() as c:
        r = c.get("/api/workspace/overview", headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["workspace_id"] == _ctx["workspace_id"]
    assert data["name"] == TEST_BUSINESS
    assert data["tier"] == "free"


# ─────────────────────────────────────────────────────────────────────────────
# Flow 14 – Update workspace settings (returns {status: updated})
# ─────────────────────────────────────────────────────────────────────────────

def test_14_update_workspace_settings():
    payload = {
        "fallback_msg": "We will get back to you shortly!",
        "alert_email": f"alerts_{_RUN_ID}@flowtest.com",
        "agents_enabled": False,
        "escalation_sensitivity": "high",
        "escalation_keywords": ["urgent", "help", "problem"],
    }
    with client() as c:
        r = c.put("/api/workspace/settings", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "updated"


# ─────────────────────────────────────────────────────────────────────────────
# Flow 15 – Canned responses CRUD + free-tier limit (max 5)
# ─────────────────────────────────────────────────────────────────────────────

def test_15a_create_canned_response():
    # NOTE: canned-responses endpoint requires NO trailing slash
    with client() as c:
        r = c.post("/api/canned-responses", json={
            "name": "Greeting",
            "content": "Hello! Thanks for reaching out. How can we assist you today?",
            "shortcut": "/greet",
        }, headers=auth_headers())
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert data["name"] == "Greeting"
    assert data["shortcut"] == "/greet"
    _ctx["canned_id"] = data["id"]


def test_15b_fill_to_tier_limit():
    """Add 4 more responses to reach the free-tier cap of 5."""
    with client() as c:
        for i in range(2, 6):
            r = c.post("/api/canned-responses", json={
                "name": f"Response {i}",
                "content": f"Canned reply number {i}.",
            }, headers=auth_headers())
            assert r.status_code in (200, 201), (
                f"Creating response {i} failed: {r.text}"
            )


def test_15c_over_limit_returns_4xx():
    """6th canned response on free tier must be rejected (402 or 403)."""
    with client() as c:
        r = c.post("/api/canned-responses", json={
            "name": "Over Limit",
            "content": "This should be rejected.",
        }, headers=auth_headers())
    assert r.status_code in (402, 403), (
        f"Expected tier-limit rejection (402/403) but got {r.status_code}: {r.text}"
    )
    assert "limit" in r.json()["detail"].lower() or "tier" in r.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Flow 16 – List canned responses
# ─────────────────────────────────────────────────────────────────────────────

def test_16_list_canned_responses():
    with client() as c:
        r = c.get("/api/canned-responses", headers=auth_headers())
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    assert len(items) == 5  # exactly at the free-tier cap
    assert _ctx["canned_id"] in [item["id"] for item in items]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 17 – Update canned response
# ─────────────────────────────────────────────────────────────────────────────

def test_17_update_canned_response():
    with client() as c:
        r = c.put(
            f"/api/canned-responses/{_ctx['canned_id']}",
            json={"name": "Welcome", "content": "Welcome! Let us know how we can help."},
            headers=auth_headers(),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Welcome"
    assert data["content"] == "Welcome! Let us know how we can help."


# ─────────────────────────────────────────────────────────────────────────────
# Flow 18 – Delete canned response
# ─────────────────────────────────────────────────────────────────────────────

def test_18_delete_canned_response():
    with client() as c:
        r = c.delete(
            f"/api/canned-responses/{_ctx['canned_id']}",
            headers=auth_headers(),
        )
    assert r.status_code in (200, 204), r.text

    # Verify it's gone
    with client() as c:
        items = c.get("/api/canned-responses", headers=auth_headers()).json()
    assert _ctx["canned_id"] not in [item["id"] for item in items]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 19 – List conversations (should be empty for a new workspace)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason=(
        "DB schema bug: 'conversations.metadata' column missing. "
        "Deploy migration 014_fix_missing_columns to fix."
    ),
    strict=False,
)
def test_19_list_conversations_empty():
    with client() as c:
        r = c.get("/api/conversations/", headers=auth_headers())
    assert r.status_code == 200, (
        f"Conversations endpoint returned {r.status_code}: {r.text}\n"
        "Run migration 014 on the deployed DB to add missing columns."
    )
    data = r.json()
    assert "conversations" in data
    assert isinstance(data["conversations"], list)
    assert data["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Flow 20 – Delete channel
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason=(
        "DB schema bug: 'contacts.email' column missing. "
        "The cascade-delete queries contacts, which fails. "
        "Deploy migration 014_fix_missing_columns to fix."
    ),
    strict=False,
)
def test_20_delete_channel():
    with client() as c:
        r = c.delete(f"/api/channels/{_ctx['channel_id']}", headers=auth_headers())
    assert r.status_code == 200, (
        f"Channel delete returned {r.status_code}: {r.text}\n"
        "Run migration 014 on the deployed DB to add missing columns."
    )
    assert r.json()["message"] == "Channel deleted successfully"

    # Verify it's gone
    with client() as c:
        channels = c.get("/api/channels/", headers=auth_headers()).json()
    assert _ctx["channel_id"] not in [ch["id"] for ch in channels]


# ─────────────────────────────────────────────────────────────────────────────
# Flow 21 – Deleted channel returns 404
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    reason="Depends on test_20 which is currently failing due to DB schema bug.",
    strict=False,
)
def test_21_get_deleted_channel_404():
    """Only meaningful if test_20 passed and actually deleted the channel."""
    if not _ctx.get("channel_id"):
        pytest.skip("Channel was never created")
    with client() as c:
        r = c.get(f"/api/channels/{_ctx['channel_id']}", headers=auth_headers())
    assert r.status_code == 404
