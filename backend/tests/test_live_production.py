"""
Live Production API Tests
Tests against https://api.parthavpovil.in
Run with: python -m pytest tests/test_live_production.py -v
"""
import pytest
import requests
import time
import uuid

BASE_URL = "https://api.parthavpovil.in"

# Shared state across tests
_state = {}


SESSION = requests.Session()


def _headers(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def get(path, token=None, **kwargs):
    resp = SESSION.get(f"{BASE_URL}{path}", headers=_headers(token), allow_redirects=False, **kwargs)
    # Follow 307/308 redirect while keeping Authorization header
    if resp.status_code in (301, 302, 307, 308):
        location = resp.headers.get("Location", "")
        if not location.startswith("http"):
            location = BASE_URL + location
        resp = SESSION.get(location, headers=_headers(token), **kwargs)
    return resp


def post(path, data=None, token=None, **kwargs):
    resp = SESSION.post(f"{BASE_URL}{path}", json=data, headers=_headers(token), allow_redirects=False, **kwargs)
    if resp.status_code in (301, 302, 307, 308):
        location = resp.headers.get("Location", "")
        if not location.startswith("http"):
            location = BASE_URL + location
        resp = SESSION.post(location, json=data, headers=_headers(token), **kwargs)
    return resp


# ─── Health ──────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self):
        r = get("/health")
        assert r.status_code == 200

    def test_health_body(self):
        r = get("/health")
        data = r.json()
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


# ─── Auth: Register ───────────────────────────────────────────────────────────

class TestAuthRegister:
    EMAIL = f"livetest_{uuid.uuid4().hex[:8]}@example.com"
    PASSWORD = "TestPass123!"
    BUSINESS = f"LiveTest Co {uuid.uuid4().hex[:6]}"

    def test_register_new_user(self):
        r = post("/api/auth/register", {
            "email": self.EMAIL,
            "password": self.PASSWORD,
            "business_name": self.BUSINESS,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        assert data["user"]["email"] == self.EMAIL
        assert data["workspace"]["name"] == self.BUSINESS
        _state["token"] = data["access_token"]
        _state["email"] = self.EMAIL
        _state["password"] = self.PASSWORD
        _state["workspace_slug"] = data["workspace"]["slug"]
        _state["workspace_id"] = data["workspace"]["id"]

    def test_register_duplicate_email_rejected(self):
        r = post("/api/auth/register", {
            "email": self.EMAIL,
            "password": self.PASSWORD,
            "business_name": "Duplicate Inc",
        })
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"].lower()


# ─── Auth: Login ─────────────────────────────────────────────────────────────

class TestAuthLogin:
    def test_login_valid_credentials(self):
        assert "email" in _state, "Run TestAuthRegister first"
        r = post("/api/auth/login", {
            "email": _state["email"],
            "password": _state["password"],
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data
        _state["token"] = data["access_token"]

    def test_login_wrong_password(self):
        r = post("/api/auth/login", {
            "email": _state.get("email", "x@x.com"),
            "password": "wrongpassword",
        })
        assert r.status_code == 401

    def test_login_nonexistent_user(self):
        r = post("/api/auth/login", {
            "email": "nobody_does_not_exist@example.com",
            "password": "whatever",
        })
        assert r.status_code == 401


# ─── Auth: /me ────────────────────────────────────────────────────────────────

class TestAuthMe:
    def test_me_with_valid_token(self):
        assert "token" in _state, "Run TestAuthLogin first"
        r = get("/api/auth/me", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == _state["email"]

    def test_me_without_token_rejected(self):
        r = get("/api/auth/me")
        assert r.status_code in (401, 403)

    def test_me_with_bad_token_rejected(self):
        r = get("/api/auth/me", token="bad.token.here")
        assert r.status_code in (401, 403)


# ─── Agents ──────────────────────────────────────────────────────────────────

class TestAgents:
    def test_list_agents_authenticated(self):
        assert "token" in _state
        r = get("/api/agents", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_agents_unauthenticated(self):
        r = get("/api/agents")
        assert r.status_code in (401, 403)

    def test_invite_agent(self):
        agent_email = f"agent_{uuid.uuid4().hex[:6]}@example.com"
        r = post("/api/agents/invite", {
            "email": agent_email,
            "name": "Test Agent",
        }, token=_state["token"])
        # Free tier allows 0 agents — expect 402 tier limit or 200 success
        assert r.status_code in (200, 402), r.text
        if r.status_code == 200:
            data = r.json()
            assert data["email"] == agent_email
            _state["invited_agent_email"] = agent_email
            _state["invited_agent_id"] = data["id"]
        else:
            assert "tier" in r.json().get("detail", "").lower() or "limit" in r.json().get("detail", "").lower()


# ─── Channels ─────────────────────────────────────────────────────────────────

class TestChannels:
    def test_list_channels_authenticated(self):
        r = get("/api/channels", token=_state["token"])
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_list_channels_unauthenticated(self):
        r = get("/api/channels")
        assert r.status_code in (401, 403)


# ─── Conversations ────────────────────────────────────────────────────────────

class TestConversations:
    def test_list_conversations_authenticated(self):
        r = get("/api/conversations", token=_state["token"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, (list, dict))

    def test_list_conversations_unauthenticated(self):
        r = get("/api/conversations")
        assert r.status_code in (401, 403)


# ─── Documents ────────────────────────────────────────────────────────────────

class TestDocuments:
    def test_list_documents_authenticated(self):
        r = get("/api/documents", token=_state["token"])
        assert r.status_code == 200, r.text

    def test_list_documents_unauthenticated(self):
        r = get("/api/documents")
        assert r.status_code in (401, 403)


# ─── Metrics ──────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_middleware_metrics_endpoint(self):
        r = get("/metrics/middleware")
        assert r.status_code == 200, r.text

    def test_metrics_authenticated(self):
        r = get("/api/metrics", token=_state["token"])
        assert r.status_code in (200, 404)  # endpoint may vary


# ─── Security ─────────────────────────────────────────────────────────────────

class TestSecurity:
    def test_expired_token_rejected(self):
        # Tampered JWT
        bad = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkhhY2tlciIsImlhdCI6MTV9.fake_sig"
        r = get("/api/auth/me", token=bad)
        assert r.status_code in (401, 403)

    def test_sql_injection_in_login(self):
        r = post("/api/auth/login", {
            "email": "' OR '1'='1",
            "password": "anything",
        })
        # Should return validation error or 401, never 200
        assert r.status_code in (400, 401, 422)

    def test_missing_content_type_handled(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          data="not json",
                          headers={"Content-Type": "text/plain"})
        assert r.status_code in (400, 415, 422)


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
        assert p95 < 2.0, f"p95 latency {p95:.2f}s exceeds 2s"

    def test_concurrent_health_checks(self):
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(get, "/health") for _ in range(10)]
            results = [f.result() for f in futures]
        assert all(r.status_code == 200 for r in results)
