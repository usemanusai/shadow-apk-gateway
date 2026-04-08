"""Tests for the inference engine — risk tags, auth, pagination, idempotency."""

import pytest

from packages.trace_model.src.inference import (
    infer_auth_requirements,
    infer_idempotency,
    infer_pagination,
    infer_risk_tags,
)
from packages.core_schema.models.action_object import AuthType, ParamSchema
from packages.core_schema.models.raw_finding import RawStaticFinding
from packages.core_schema.models.trace_record import TraceRecord


def _make_trace(**kwargs) -> TraceRecord:
    """Create a TraceRecord with sensible defaults."""
    defaults = {
        "trace_id": "trace-001",
        "app_id": "com.example.app",
        "session_id": "sess-001",
        "timestamp_ms": 1700000000000,
        "method": "GET",
        "url": "https://api.example.com/v1/users",
        "request_headers": {},
    }
    defaults.update(kwargs)
    return TraceRecord(**defaults)


def _make_finding(**kwargs) -> RawStaticFinding:
    """Create a RawStaticFinding with sensible defaults."""
    defaults = {
        "finding_id": "f-001",
        "parser_name": "retrofit",
        "source_file": "com/example/Api.smali",
    }
    defaults.update(kwargs)
    return RawStaticFinding(**defaults)


class TestRiskTagInference:
    """Test risk tag inference from URLs and trace data."""

    def test_login_from_url(self):
        tags = infer_risk_tags("/api/auth/login", [], [])
        assert "login" in tags

    def test_login_from_signin_url(self):
        tags = infer_risk_tags("/api/signin", [], [])
        assert "login" in tags

    def test_login_from_token_url(self):
        tags = infer_risk_tags("/api/oauth/token", [], [])
        assert "login" in tags

    def test_login_from_response_header(self):
        trace = _make_trace(
            response_headers={"Set-Cookie": "session=abc123; HttpOnly"},
        )
        tags = infer_risk_tags("/api/session", [trace], [])
        assert "login" in tags

    def test_login_from_response_body_tokens(self):
        trace = _make_trace(
            response_body_parsed={"access_token": "eyJ...", "refresh_token": "abc"},
        )
        tags = infer_risk_tags("/api/something", [trace], [])
        assert "login" in tags

    def test_payment_from_url(self):
        tags = infer_risk_tags("/api/checkout/pay", [], [])
        assert "payment" in tags

    def test_payment_from_request_body(self):
        trace = _make_trace(
            method="POST",
            request_body_parsed={"amount": 99.99, "card_number": "4111111111111111"},
        )
        tags = infer_risk_tags("/api/charge", [trace], [])
        assert "payment" in tags

    def test_2fa_from_url(self):
        tags = infer_risk_tags("/api/otp/verify", [], [])
        assert "2fa" in tags

    def test_2fa_from_mfa_url(self):
        tags = infer_risk_tags("/api/mfa/challenge", [], [])
        assert "2fa" in tags

    def test_device_binding_from_headers(self):
        trace = _make_trace(
            request_headers={"X-Device-Id": "abc123", "Content-Type": "application/json"},
        )
        tags = infer_risk_tags("/api/register", [trace], [])
        assert "device_binding" in tags

    def test_device_binding_from_body(self):
        trace = _make_trace(
            request_body_parsed={"android_id": "a1b2c3d4e5f6"},
        )
        tags = infer_risk_tags("/api/device/register", [trace], [])
        assert "device_binding" in tags

    def test_captcha_detection(self):
        trace = _make_trace(
            response_body_parsed={"captcha_url": "https://www.google.com/recaptcha"},
        )
        tags = infer_risk_tags("/api/submit", [trace], [])
        assert "captcha" in tags

    def test_no_tags_for_normal_endpoint(self):
        tags = infer_risk_tags("/api/v1/products", [], [])
        assert tags == []

    def test_multiple_tags(self):
        """Endpoint with multiple signals should have multiple tags."""
        trace = _make_trace(
            request_headers={"X-Device-Id": "abc"},
            request_body_parsed={"amount": 50},
        )
        tags = infer_risk_tags("/api/pay/checkout", [trace], [])
        assert "payment" in tags
        assert "device_binding" in tags

    def test_tags_are_sorted(self):
        tags = infer_risk_tags("/api/auth/login", [], [])
        assert tags == sorted(tags)


class TestAuthRequirementInference:
    """Test auth requirement inference from request headers."""

    def test_bearer_auth(self):
        trace = _make_trace(
            request_headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.Rq8IjqbaZ7lqXI0PUq"},
        )
        result = infer_auth_requirements([trace])
        assert AuthType.BEARER in result

    def test_basic_auth(self):
        trace = _make_trace(
            request_headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        result = infer_auth_requirements([trace])
        assert AuthType.BASIC in result

    def test_api_key_auth(self):
        trace = _make_trace(
            request_headers={"X-API-Key": "sk-12345abcde"},
        )
        result = infer_auth_requirements([trace])
        assert AuthType.APIKEY in result

    def test_cookie_auth(self):
        trace = _make_trace(
            request_headers={"Cookie": "session=abc123"},
        )
        result = infer_auth_requirements([trace])
        assert AuthType.COOKIE in result

    def test_no_auth(self):
        trace = _make_trace(
            request_headers={"Content-Type": "application/json"},
        )
        result = infer_auth_requirements([trace])
        assert AuthType.NONE in result

    def test_multiple_auth_types(self):
        trace = _make_trace(
            request_headers={
                "Authorization": "Bearer eyJ...",
                "Cookie": "session=xyz",
                "X-API-Key": "key123",
            },
        )
        result = infer_auth_requirements([trace])
        assert AuthType.BEARER in result
        assert AuthType.COOKIE in result
        assert AuthType.APIKEY in result

    def test_empty_traces_returns_none(self):
        result = infer_auth_requirements([])
        assert AuthType.NONE in result


class TestPaginationInference:
    """Test pagination pattern inference."""

    def test_cursor_from_params(self):
        params = [ParamSchema(name="cursor", location="query", required=False, type="string")]
        is_paginated, pattern = infer_pagination("/api/items", [], params)
        assert is_paginated is True
        assert pattern == "cursor"

    def test_offset_from_params(self):
        params = [
            ParamSchema(name="offset", location="query", required=False, type="integer"),
            ParamSchema(name="limit", location="query", required=False, type="integer"),
        ]
        is_paginated, pattern = infer_pagination("/api/items", [], params)
        assert is_paginated is True
        assert pattern == "offset"

    def test_page_from_params(self):
        params = [ParamSchema(name="page", location="query", required=False, type="integer")]
        is_paginated, pattern = infer_pagination("/api/items", [], params)
        assert is_paginated is True
        assert pattern == "page"

    def test_cursor_from_response_body(self):
        trace = _make_trace(
            response_body_parsed={"data": [], "next_cursor": "abc123"},
        )
        is_paginated, pattern = infer_pagination("/api/items", [trace], [])
        assert is_paginated is True
        assert pattern == "cursor"

    def test_page_from_response_body(self):
        trace = _make_trace(
            response_body_parsed={"items": [], "total_pages": 5, "next_page": 2},
        )
        is_paginated, pattern = infer_pagination("/api/items", [trace], [])
        assert is_paginated is True
        assert pattern == "page"

    def test_offset_from_response_body(self):
        trace = _make_trace(
            response_body_parsed={"items": [], "total": 100, "offset": 0, "limit": 20},
        )
        is_paginated, pattern = infer_pagination("/api/items", [trace], [])
        assert is_paginated is True
        assert pattern == "offset"

    def test_not_paginated(self):
        is_paginated, pattern = infer_pagination("/api/user/profile", [], [])
        assert is_paginated is None
        assert pattern is None

    def test_cursor_from_url(self):
        params: list[ParamSchema] = []
        is_paginated, pattern = infer_pagination("/api/cursor/items", [], params)
        assert is_paginated is True
        assert pattern == "cursor"


class TestIdempotencyInference:
    """Test HTTP method-based idempotency inference."""

    def test_get_is_idempotent(self):
        assert infer_idempotency("GET") is True

    def test_put_is_idempotent(self):
        assert infer_idempotency("PUT") is True

    def test_delete_is_idempotent(self):
        assert infer_idempotency("DELETE") is True

    def test_head_is_idempotent(self):
        assert infer_idempotency("HEAD") is True

    def test_post_is_not_idempotent(self):
        assert infer_idempotency("POST") is False

    def test_patch_is_not_idempotent(self):
        assert infer_idempotency("PATCH") is False

    def test_unknown_method_returns_none(self):
        assert infer_idempotency("CUSTOM") is None

    def test_case_insensitive(self):
        assert infer_idempotency("get") is True
        assert infer_idempotency("post") is False
