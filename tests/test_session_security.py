"""Tests for Session Manager and Auth Middleware security hardening."""

import json
import os
import time
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from apps.gateway.src.session import SessionManager, Session, _resolve_fernet_key
from apps.gateway.src.auth import AuthMiddleware, _constant_time_compare
from apps.gateway.src.audit import AuditLogger, _mask_headers, _mask_body, REDACTED


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Middleware — HMAC Constant-Time Comparison
# ═══════════════════════════════════════════════════════════════════════════════


class TestConstantTimeCompare:
    """Test HMAC constant-time comparison."""

    def test_matching_keys(self):
        assert _constant_time_compare("secret-key-123", "secret-key-123") is True

    def test_non_matching_keys(self):
        assert _constant_time_compare("wrong-key", "secret-key-123") is False

    def test_empty_vs_non_empty(self):
        assert _constant_time_compare("", "secret-key-123") is False

    def test_both_empty(self):
        assert _constant_time_compare("", "") is True

    def test_similar_keys_differ_by_one_char(self):
        assert _constant_time_compare("secret-key-12x", "secret-key-123") is False

    def test_unicode_keys(self):
        assert _constant_time_compare("🔐key-unicode", "🔐key-unicode") is True
        assert _constant_time_compare("🔐key-unicode", "🔐key-unicodx") is False


class TestAuthMiddlewareConfig:
    """Test AuthMiddleware configuration."""

    def test_reads_from_env_variable(self):
        with patch.dict(os.environ, {"GATEWAY_API_KEY": "env-secret-key"}):
            middleware = AuthMiddleware(app=None, api_key=None)
            assert middleware.api_key == "env-secret-key"

    def test_explicit_key_overrides_env(self):
        with patch.dict(os.environ, {"GATEWAY_API_KEY": "env-key"}):
            middleware = AuthMiddleware(app=None, api_key="explicit-key")
            assert middleware.api_key == "explicit-key"

    def test_no_key_means_no_auth(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GATEWAY_API_KEY", None)
            middleware = AuthMiddleware(app=None, api_key=None)
            assert middleware.api_key == ""


class TestAuthMiddlewareIntegration:
    """Integration tests for auth middleware with FastAPI."""

    def test_health_endpoint_exempt(self):
        """Health endpoint should be accessible without API key."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        test_app = FastAPI()
        test_app.add_middleware(AuthMiddleware, api_key="test-secret")

        @test_app.get("/health")
        def health():
            return {"status": "ok"}

        @test_app.get("/protected")
        def protected():
            return {"data": "secret"}

        client = TestClient(test_app, raise_server_exceptions=False)

        # Health should work without key
        res = client.get("/health")
        assert res.status_code == 200

        # Protected should fail without key
        res = client.get("/protected")
        assert res.status_code == 401

    def test_valid_header_key_passes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        test_app = FastAPI()
        test_app.add_middleware(AuthMiddleware, api_key="my-secret")

        @test_app.get("/data")
        def data():
            return {"ok": True}

        client = TestClient(test_app, raise_server_exceptions=False)
        res = client.get("/data", headers={"X-Gateway-Key": "my-secret"})
        assert res.status_code == 200

    def test_valid_query_key_passes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        test_app = FastAPI()
        test_app.add_middleware(AuthMiddleware, api_key="my-secret")

        @test_app.get("/data")
        def data():
            return {"ok": True}

        client = TestClient(test_app, raise_server_exceptions=False)
        res = client.get("/data?api_key=my-secret")
        assert res.status_code == 200

    def test_invalid_key_rejected(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        test_app = FastAPI()
        test_app.add_middleware(AuthMiddleware, api_key="my-secret")

        @test_app.get("/data")
        def data():
            return {"ok": True}

        client = TestClient(test_app, raise_server_exceptions=False)
        res = client.get("/data", headers={"X-Gateway-Key": "wrong-key"})
        assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Session Manager — Fernet Encryption + Rotation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFernetKeyResolution:
    """Test Fernet key resolution from environment."""

    def test_generates_key_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GATEWAY_FERNET_KEY", None)
            key = _resolve_fernet_key()
            assert key is not None
            # Should be a valid Fernet key
            Fernet(key)

    def test_uses_env_key_when_set(self):
        valid_key = Fernet.generate_key().decode("utf-8")
        with patch.dict(os.environ, {"GATEWAY_FERNET_KEY": valid_key}):
            key = _resolve_fernet_key()
            assert key == valid_key.encode("utf-8")

    def test_fallback_on_invalid_env_key(self):
        with patch.dict(os.environ, {"GATEWAY_FERNET_KEY": "not-a-valid-key"}):
            key = _resolve_fernet_key()
            # Should generate a new key, not crash
            Fernet(key)


class TestSessionEncryption:
    """Test session credential encryption roundtrip."""

    @pytest.mark.asyncio
    async def test_credential_encryption_roundtrip(self):
        manager = SessionManager()
        creds = {"username": "admin", "password": "supersecret123"}

        session = await manager.start_session("app1", "tenant1", creds)
        assert session.session_id

        # Decrypt and verify
        decrypted = manager._decrypt_credentials("app1", "tenant1")
        assert decrypted == creds

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_none(self):
        manager = SessionManager()
        result = manager._decrypt_credentials("nonexistent", "tenant")
        assert result is None

    @pytest.mark.asyncio
    async def test_session_expiry(self):
        manager = SessionManager(ttl_seconds=1)
        session = await manager.start_session("app1", "t1", {})

        # Session should be active
        auth = manager.get_session("app1", "t1")
        assert auth is not None

        # Wait for expiry
        time.sleep(1.1)
        auth = manager.get_session("app1", "t1")
        assert auth is None

    @pytest.mark.asyncio
    async def test_session_clear(self):
        manager = SessionManager()
        session = await manager.start_session("app1", "t1", {"key": "val"})

        manager.clear_session("app1", session.session_id)
        auth = manager.get_session("app1", "t1")
        assert auth is None

    @pytest.mark.asyncio
    async def test_clear_all_sessions(self):
        manager = SessionManager()
        await manager.start_session("app1", "t1", {})
        await manager.start_session("app1", "t2", {})

        manager.clear_all_sessions("app1")
        assert manager.get_session("app1", "t1") is None
        assert manager.get_session("app1", "t2") is None

    def test_execution_counting(self):
        manager = SessionManager(rotation_threshold=5)
        manager._sessions["app1:t1"] = Session(
            session_id="sid",
            app_id="app1",
            tenant_id="t1",
            created_at=time.time(),
            expires_at=time.time() + 3600,
        )

        for i in range(4):
            manager.record_execution("app1", "t1")
        assert manager._sessions["app1:t1"].execution_count == 4


# ═══════════════════════════════════════════════════════════════════════════════
# Audit Logger — Header + Body Masking
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditHeaderMasking:
    """Test sensitive header masking in audit logs."""

    def test_masks_authorization_header(self):
        headers = {"Authorization": "Bearer eyJ...", "Content-Type": "application/json"}
        masked = _mask_headers(headers)
        assert masked["Authorization"] == REDACTED
        assert masked["Content-Type"] == "application/json"

    def test_masks_cookie_header(self):
        headers = {"Cookie": "session=abc123", "Accept": "text/html"}
        masked = _mask_headers(headers)
        assert masked["Cookie"] == REDACTED
        assert masked["Accept"] == "text/html"

    def test_masks_api_key_header(self):
        headers = {"X-API-Key": "sk-secret", "User-Agent": "TestClient"}
        masked = _mask_headers(headers)
        assert masked["X-API-Key"] == REDACTED
        assert masked["User-Agent"] == "TestClient"

    def test_masks_gateway_key_header(self):
        headers = {"X-Gateway-Key": "gateway-secret"}
        masked = _mask_headers(headers)
        assert masked["X-Gateway-Key"] == REDACTED

    def test_case_insensitive_matching(self):
        headers = {"authorization": "Bearer token", "COOKIE": "sess=abc"}
        masked = _mask_headers(headers)
        assert masked["authorization"] == REDACTED
        assert masked["COOKIE"] == REDACTED


class TestAuditBodyMasking:
    """Test sensitive body field masking in audit logs."""

    def test_masks_password_field(self):
        body = {"username": "admin", "password": "secret123"}
        masked = _mask_body(body)
        assert masked["username"] == "admin"
        assert masked["password"] == REDACTED

    def test_masks_token_field(self):
        body = {"token": "eyJ...", "data": "safe"}
        masked = _mask_body(body)
        assert masked["token"] == REDACTED
        assert masked["data"] == "safe"

    def test_masks_card_number(self):
        body = {"card_number": "4111111111111111", "amount": 99.99}
        masked = _mask_body(body)
        assert masked["card_number"] == REDACTED
        assert masked["amount"] == 99.99

    def test_recursive_masking(self):
        body = {
            "user": {
                "name": "Alice",
                "settings": {"api_key": "sk-secret", "role": "admin"},
            }
        }
        masked = _mask_body(body)
        assert masked["user"]["name"] == "Alice"
        assert masked["user"]["settings"]["api_key"] == REDACTED
        assert masked["user"]["settings"]["role"] == "admin"

    def test_empty_body(self):
        assert _mask_body({}) == {}


class TestAuditLoggerHardened:
    """Test the full hardened audit logger."""

    def test_logs_with_headers_and_body(self):
        logger = AuditLogger()
        entry = logger.log_execution(
            app_id="test_app",
            action_id="action_1",
            tenant_id="default",
            request_url="https://api.example.com/login",
            response_status=200,
            latency_ms=150,
            request_headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
            request_body={"username": "admin", "password": "p@ssw0rd"},
        )

        assert entry["request_headers"]["Authorization"] == REDACTED
        assert entry["request_headers"]["Content-Type"] == "application/json"
        assert entry["request_body"]["username"] == "admin"
        assert entry["request_body"]["password"] == REDACTED

    def test_url_param_masking(self):
        logger = AuditLogger()
        entry = logger.log_execution(
            app_id="app",
            action_id="act",
            tenant_id="t",
            request_url="https://api.com/search?token=secret&query=hello",
            response_status=200,
            latency_ms=50,
            sensitive_params=["token"],
        )
        assert "secret" not in entry["request_url"]
        assert REDACTED in entry["request_url"]
        assert "query=hello" in entry["request_url"]

    def test_audit_to_file(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=str(log_file))
        logger.log_execution("app", "act", "t", "http://api.com", 200, 100)

        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["app_id"] == "app"
