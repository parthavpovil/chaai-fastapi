"""
Strategic break-point tests.

This file covers the foundational invariants that, if broken, take the whole
backend down silently in CI but loudly in production:

  * Configuration & app boot — modules import cleanly, secrets are loaded.
  * Authentication — JWT round-trip, expiration, tampering, password/PIN hashing.
  * Credential encryption — AES-256-CBC round-trip, ciphertext uniqueness,
    tamper detection, salt isolation.
  * Webhook signature verification — Meta (WhatsApp/Instagram), Telegram secret,
    Resend (Svix), Brevo, and the routers' internal helpers.
  * Tier limits configuration — every advertised tier is present and the
    business-critical keys exist with the right shapes.
  * Pydantic schema validation — registration sanitisation, email/password rules.
  * Webhook security utilities — secure token generation, process secret check.

All tests are pure unit tests with no database dependency, so they run in
seconds and can be relied on as a smoke screen before any heavier integration
suite. The fixtures patch settings where needed so the tests do not depend on
the CI environment having anything beyond what test.yml already sets.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. Configuration & application boot
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigurationBoot:
    """If config or routers can't import, every other test is meaningless."""

    def test_settings_loads_required_secrets(self):
        from app.config import settings

        assert settings.JWT_SECRET_KEY, "JWT_SECRET_KEY must be set in env"
        assert settings.JWT_ALGORITHM == "HS256"
        assert settings.ENCRYPTION_KEY, "ENCRYPTION_KEY must be set in env"
        assert settings.PROCESS_SECRET, "PROCESS_SECRET must be set in env"
        assert settings.JWT_EXPIRE_MINUTES > 0

    def test_tier_limits_constant_loads(self):
        from app.config import TIER_LIMITS

        for tier in ("free", "starter", "growth", "pro"):
            assert tier in TIER_LIMITS, f"tier '{tier}' missing from TIER_LIMITS"

    def test_critical_modules_import(self):
        """A regression here means the app can't even boot under uvicorn."""
        import app.config  # noqa: F401
        import app.database  # noqa: F401
        import app.services.auth_service  # noqa: F401
        import app.services.encryption  # noqa: F401
        import app.services.webhook_security  # noqa: F401
        import app.services.tier_manager  # noqa: F401
        import app.services.rag_engine  # noqa: F401
        import app.services.escalation_router  # noqa: F401
        import app.services.message_processor  # noqa: F401
        import app.routers.auth  # noqa: F401
        import app.routers.webhooks  # noqa: F401
        import app.routers.webchat  # noqa: F401
        import app.routers.websocket  # noqa: F401

    def test_encryption_singleton_initialised(self):
        from app.services.encryption import encryption_service

        assert encryption_service is not None, (
            "encryption_service failed to initialise — check ENCRYPTION_KEY env var"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Authentication: JWT + password/PIN hashing
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthService:

    def test_jwt_round_trip_preserves_claims(self):
        from app.services.auth_service import AuthService

        user_id = uuid4()
        workspace_id = uuid4()
        token = AuthService.create_access_token(
            user_id=user_id,
            email="user@example.com",
            role="owner",
            workspace_id=workspace_id,
        )
        assert isinstance(token, str) and token.count(".") == 2

        payload = AuthService.decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == str(user_id)
        assert payload["email"] == "user@example.com"
        assert payload["role"] == "owner"
        assert payload["workspace_id"] == str(workspace_id)
        assert payload["jti"]  # unique id, used by logout blocklist

    def test_jwt_token_for_pending_agent_has_no_workspace_id(self):
        from app.services.auth_service import AuthService

        token = AuthService.create_access_token(
            user_id=uuid4(),
            email="agent@example.com",
            role="agent",
            workspace_id=None,
        )
        payload = AuthService.decode_access_token(token)
        assert payload is not None
        assert payload["workspace_id"] is None

    def test_jwt_rejects_tampered_signature(self):
        from app.services.auth_service import AuthService

        token = AuthService.create_access_token(
            user_id=uuid4(),
            email="user@example.com",
            role="owner",
        )
        # flip the final character of the signature
        bad_token = token[:-1] + ("a" if token[-1] != "a" else "b")
        assert AuthService.decode_access_token(bad_token) is None

    def test_jwt_rejects_garbage(self):
        from app.services.auth_service import AuthService

        assert AuthService.decode_access_token("not-a-jwt") is None
        assert AuthService.decode_access_token("") is None

    def test_jwt_is_token_expired_for_past_token(self):
        from app.services.auth_service import AuthService

        token = AuthService.create_access_token(
            user_id=uuid4(),
            email="user@example.com",
            role="owner",
            expires_delta=timedelta(seconds=-1),
        )
        assert AuthService.is_token_expired(token) is True

    def test_jwt_get_helpers_return_uuid(self):
        from app.services.auth_service import AuthService

        user_id = uuid4()
        workspace_id = uuid4()
        token = AuthService.create_access_token(
            user_id=user_id,
            email="user@example.com",
            role="owner",
            workspace_id=workspace_id,
        )
        assert AuthService.get_user_id_from_token(token) == user_id
        assert AuthService.get_workspace_id_from_token(token) == workspace_id

    def test_password_hash_and_verify(self):
        from app.services.auth_service import AuthService

        hashed = AuthService.hash_password("correct horse battery staple")
        assert hashed != "correct horse battery staple"
        assert hashed.startswith("$2")  # bcrypt prefix
        assert AuthService.verify_password("correct horse battery staple", hashed)
        assert not AuthService.verify_password("wrong password", hashed)

    def test_password_hash_handles_72_byte_truncation(self):
        """Bcrypt only uses the first 72 bytes — both store and verify must
        truncate identically or long passwords would silently reject."""
        from app.services.auth_service import AuthService

        long_password = "a" * 100
        hashed = AuthService.hash_password(long_password)
        # The first 72 bytes are what bcrypt actually compares.
        assert AuthService.verify_password(long_password, hashed)
        assert AuthService.verify_password("a" * 72, hashed)

    def test_pin_hash_and_verify(self):
        from app.services.auth_service import AuthService

        hashed = AuthService.hash_pin("1234")
        assert AuthService.verify_pin("1234", hashed)
        assert not AuthService.verify_pin("0000", hashed)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Credential encryption: AES-256-CBC + PBKDF2
# ─────────────────────────────────────────────────────────────────────────────


class TestEncryption:

    def test_encrypt_decrypt_round_trip(self):
        from app.services.encryption import encrypt_credential, decrypt_credential

        secret = "bot-token-1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ciphertext = encrypt_credential(secret)
        assert ciphertext != secret
        assert decrypt_credential(ciphertext) == secret

    def test_encrypt_unicode_payload(self):
        from app.services.encryption import encrypt_credential, decrypt_credential

        payload = "héllo — 🌍 — ünîcödé"
        assert decrypt_credential(encrypt_credential(payload)) == payload

    def test_encrypt_same_plaintext_yields_different_ciphertexts(self):
        """Random salt + IV must make every ciphertext unique. If this fails,
        someone replaced PBKDF2 random salt with a fixed one — a serious
        regression that would also leak that two channels share a credential."""
        from app.services.encryption import encrypt_credential

        a = encrypt_credential("same-secret")
        b = encrypt_credential("same-secret")
        assert a != b

    def test_decrypt_rejects_tampered_ciphertext(self):
        """A bit-flip in the ciphertext should fail PKCS#7 unpadding and raise."""
        from app.services.encryption import (
            encrypt_credential,
            decrypt_credential,
            EncryptionError,
        )

        ciphertext = encrypt_credential("sensitive-token")
        raw = bytearray(base64.b64decode(ciphertext))
        raw[-1] ^= 0x01  # flip last bit of last ciphertext byte
        tampered = base64.b64encode(bytes(raw)).decode("utf-8")

        with pytest.raises(EncryptionError):
            decrypt_credential(tampered)

    def test_decrypt_rejects_garbage_input(self):
        from app.services.encryption import decrypt_credential, EncryptionError

        with pytest.raises(EncryptionError):
            decrypt_credential("this-is-not-base64-or-anything-valid!!!")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Webhook signature verification (all platforms)
# ─────────────────────────────────────────────────────────────────────────────


class TestMetaWebhookSignature:
    """WhatsApp and Instagram both use Meta's X-Hub-Signature-256 scheme."""

    @staticmethod
    def _sign(payload: bytes, secret: str) -> str:
        return "sha256=" + hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()

    def test_valid_signature_passes(self):
        from app.services.webhook_security import WebhookSecurity

        payload = b'{"object":"whatsapp_business_account"}'
        secret = "app-secret-xyz"
        assert WebhookSecurity.verify_meta_signature(
            payload, self._sign(payload, secret), secret
        )

    def test_signature_without_sha256_prefix_also_accepted(self):
        from app.services.webhook_security import WebhookSecurity

        payload = b'{"foo":"bar"}'
        secret = "s"
        bare = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert WebhookSecurity.verify_meta_signature(payload, bare, secret)

    def test_invalid_signature_rejected(self):
        from app.services.webhook_security import WebhookSecurity

        payload = b'{"foo":"bar"}'
        assert not WebhookSecurity.verify_meta_signature(
            payload, "sha256=" + ("0" * 64), "the-real-secret"
        )

    def test_payload_mutation_invalidates_signature(self):
        """If an attacker rewrites the body, signature verification must fail."""
        from app.services.webhook_security import WebhookSecurity

        original = b'{"amount":100}'
        secret = "s"
        sig = self._sign(original, secret)
        assert not WebhookSecurity.verify_meta_signature(
            b'{"amount":999999}', sig, secret
        )

    def test_missing_app_secret_raises(self):
        from app.services.webhook_security import (
            WebhookSecurity,
            WebhookSecurityError,
        )

        with pytest.raises(WebhookSecurityError):
            WebhookSecurity.verify_meta_signature(b"{}", "sha256=00", "")


class TestTelegramSecretToken:

    def test_matching_token_returns_true(self):
        from app.services.webhook_security import WebhookSecurity

        with patch("app.services.webhook_security.settings") as mock_settings:
            mock_settings.TELEGRAM_SECRET_TOKEN = "abc123"
            assert WebhookSecurity.verify_telegram_secret("abc123")

    def test_mismatched_token_returns_false(self):
        from app.services.webhook_security import WebhookSecurity

        with patch("app.services.webhook_security.settings") as mock_settings:
            mock_settings.TELEGRAM_SECRET_TOKEN = "abc123"
            assert not WebhookSecurity.verify_telegram_secret("wrong")

    def test_unset_token_raises(self):
        from app.services.webhook_security import (
            WebhookSecurity,
            WebhookSecurityError,
        )

        with patch("app.services.webhook_security.settings") as mock_settings:
            mock_settings.TELEGRAM_SECRET_TOKEN = ""
            with pytest.raises(WebhookSecurityError):
                WebhookSecurity.verify_telegram_secret("anything")


class TestProcessSecret:

    def test_matching_secret_accepted(self):
        from app.services.webhook_security import WebhookSecurity

        with patch("app.services.webhook_security.settings") as mock_settings:
            mock_settings.PROCESS_SECRET = "internal-shared-secret"
            assert WebhookSecurity.verify_process_secret("internal-shared-secret")

    def test_mismatched_secret_rejected(self):
        from app.services.webhook_security import WebhookSecurity

        with patch("app.services.webhook_security.settings") as mock_settings:
            mock_settings.PROCESS_SECRET = "internal-shared-secret"
            assert not WebhookSecurity.verify_process_secret("nope")


class TestSecureTokenGeneration:

    def test_generated_token_is_unique_and_urlsafe(self):
        from app.services.webhook_security import WebhookSecurity

        a = WebhookSecurity.generate_secure_token()
        b = WebhookSecurity.generate_secure_token()
        assert a != b
        # token_urlsafe alphabet only contains [A-Za-z0-9_-]
        assert all(c.isalnum() or c in "-_" for c in a)
        # length=32 bytes of entropy → base64url string > 32 chars
        assert len(a) >= 32


class TestResendSignature:
    """Resend uses the Svix webhook signing scheme."""

    @staticmethod
    def _sign(body: bytes, timestamp: str, secret: str) -> str:
        signed_content = f"{timestamp}.{body.decode('utf-8')}"
        return "v1," + hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def test_valid_signature_passes(self):
        from app.routers.webhooks import verify_resend_signature

        body = b'{"type":"email.delivered"}'
        ts = "1700000000"
        secret = "whsec_xxx"
        sig = self._sign(body, ts, secret)
        assert verify_resend_signature(body, sig, ts, secret)

    def test_signature_without_v1_returns_false(self):
        from app.routers.webhooks import verify_resend_signature

        # well-formed `v2,...` style but no v1 key → should reject
        assert not verify_resend_signature(
            b"{}", "v2,deadbeef", "1700000000", "secret"
        )

    def test_tampered_body_rejected(self):
        from app.routers.webhooks import verify_resend_signature

        body = b'{"type":"email.delivered"}'
        ts = "1700000000"
        secret = "whsec_xxx"
        sig = self._sign(body, ts, secret)
        assert not verify_resend_signature(
            b'{"type":"email.bounced"}', sig, ts, secret
        )

    def test_malformed_signature_does_not_raise(self):
        """Verifier must swallow parsing errors and return False, not crash
        the webhook handler."""
        from app.routers.webhooks import verify_resend_signature

        assert not verify_resend_signature(b"{}", "garbage", "1700000000", "s")


class TestBrevoSignature:

    def test_valid_signature_passes(self):
        from app.routers.webhooks import verify_brevo_signature

        body = b'{"event":"delivered"}'
        secret = "brevo-secret"
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        assert verify_brevo_signature(body, sig, secret)

    def test_invalid_signature_rejected(self):
        from app.routers.webhooks import verify_brevo_signature

        assert not verify_brevo_signature(b"{}", "00" * 32, "brevo-secret")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tier limits — shape & business invariants
# ─────────────────────────────────────────────────────────────────────────────


class TestTierLimits:

    REQUIRED_KEYS = {
        "channels",
        "ai_agents",
        "documents_max",
        "monthly_messages",
        "canned_responses",
        "has_assignment_rules",
        "has_api_access",
        "has_outbound_webhooks",
        "has_custom_ai",
        "has_export",
        "price",
    }

    @pytest.mark.parametrize("tier", ["free", "starter", "growth", "pro"])
    def test_tier_has_all_required_keys(self, tier):
        from app.config import TIER_LIMITS

        missing = self.REQUIRED_KEYS - set(TIER_LIMITS[tier])
        assert not missing, f"tier '{tier}' missing keys: {missing}"

    def test_limits_increase_monotonically_with_price(self):
        """Higher-priced tiers should never offer fewer messages or channels."""
        from app.config import TIER_LIMITS

        order = ["free", "starter", "growth", "pro"]
        for prev, curr in zip(order, order[1:]):
            assert (
                TIER_LIMITS[curr]["monthly_messages"]
                >= TIER_LIMITS[prev]["monthly_messages"]
            ), f"{curr} has fewer monthly_messages than {prev}"
            assert TIER_LIMITS[curr]["channels"] >= TIER_LIMITS[prev]["channels"]
            assert TIER_LIMITS[curr]["documents_max"] >= TIER_LIMITS[prev]["documents_max"]

    def test_free_tier_blocks_paid_features(self):
        from app.config import TIER_LIMITS

        free = TIER_LIMITS["free"]
        assert free["has_api_access"] is False
        assert free["has_outbound_webhooks"] is False
        assert free["has_custom_ai"] is False
        assert free["price"] == 0

    def test_pro_tier_unlocks_paid_features(self):
        from app.config import TIER_LIMITS

        pro = TIER_LIMITS["pro"]
        assert pro["has_api_access"] is True
        assert pro["has_outbound_webhooks"] is True
        assert pro["has_assignment_rules"] is True
        assert pro["price"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Pydantic schema validation
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthSchemas:

    def test_registration_strips_html_from_business_name(self):
        from app.schemas.auth import UserRegistrationRequest

        req = UserRegistrationRequest(
            email="founder@example.com",
            password="hunter2hunter2",
            business_name="<script>alert(1)</script>Acme",
        )
        assert "<" not in req.business_name
        assert "Acme" in req.business_name

    def test_registration_rejects_short_password(self):
        from app.schemas.auth import UserRegistrationRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UserRegistrationRequest(
                email="x@example.com", password="short", business_name="Acme"
            )

    def test_registration_rejects_invalid_email(self):
        from app.schemas.auth import UserRegistrationRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UserRegistrationRequest(
                email="not-an-email",
                password="long-enough-password",
                business_name="Acme",
            )

    def test_registration_rejects_empty_business_name(self):
        from app.schemas.auth import UserRegistrationRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UserRegistrationRequest(
                email="x@example.com",
                password="long-enough-password",
                business_name="",
            )

    def test_login_schema_accepts_minimal_fields(self):
        from app.schemas.auth import UserLoginRequest

        req = UserLoginRequest(email="user@example.com", password="any")
        assert req.email == "user@example.com"

    def test_password_reset_request_validates_email(self):
        from app.schemas.auth import ForgotPasswordRequest
        from pydantic import ValidationError

        # valid email
        ForgotPasswordRequest(email="user@example.com")
        with pytest.raises(ValidationError):
            ForgotPasswordRequest(email="not-an-email")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Webhook router internal helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookRouterHelpers:
    """The router has private helpers that translate signature failures into
    HTTPException. Regressions here would either drop legit webhooks or, worse,
    accept forged ones."""

    def test_verify_meta_signature_helper_accepts_valid(self):
        from app.routers.webhooks import _verify_meta_signature

        payload = b'{"object":"page"}'
        secret = "app-secret"
        sig = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        # Should not raise
        _verify_meta_signature(payload, sig, secret)

    def test_verify_meta_signature_helper_rejects_missing_prefix(self):
        from app.routers.webhooks import _verify_meta_signature
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _verify_meta_signature(b"{}", "no-prefix-here", "app-secret")
        assert exc.value.status_code == 401

    def test_verify_meta_signature_helper_rejects_bad_signature(self):
        from app.routers.webhooks import _verify_meta_signature
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _verify_meta_signature(b"{}", "sha256=" + "0" * 64, "app-secret")
        assert exc.value.status_code == 401

    def test_verify_telegram_secret_token_helper(self):
        from app.routers.webhooks import _verify_telegram_secret_token
        from fastapi import HTTPException

        # matching → no raise
        _verify_telegram_secret_token("the-token", "the-token")
        # mismatch → 401
        with pytest.raises(HTTPException) as exc:
            _verify_telegram_secret_token("wrong", "the-token")
        assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 8. Models import & basic instantiation
# ─────────────────────────────────────────────────────────────────────────────


class TestModelsImport:
    """If a model fails to import the SQLAlchemy metadata won't build and
    Alembic migrations & the app boot will both blow up."""

    def test_core_models_import(self):
        from app.models.workspace import Workspace  # noqa: F401
        from app.models.channel import Channel  # noqa: F401
        from app.models.contact import Contact  # noqa: F401
        from app.models.conversation import Conversation  # noqa: F401
        from app.models.message import Message  # noqa: F401
        from app.models.user import User  # noqa: F401
        from app.models.platform_setting import PlatformSetting  # noqa: F401
        from app.models.email_log import EmailLog  # noqa: F401

    def test_workspace_tablename_is_stable(self):
        """If this constant changes, every downstream join and alembic
        migration must be updated. Lock it down."""
        from app.models.workspace import Workspace

        assert Workspace.__tablename__ == "workspaces"
