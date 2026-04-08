"""Inference Engine — Infer risk tags, auth requirements, pagination, and idempotency.

Uses keyword rules and heuristics to enrich ActionObjects with metadata.
"""

from __future__ import annotations

import re
from typing import Optional

from packages.core_schema.models.action_object import AuthType, ParamSchema
from packages.core_schema.models.raw_finding import RawStaticFinding
from packages.core_schema.models.trace_record import TraceRecord


def infer_risk_tags(
    url_template: str,
    trace_records: list[TraceRecord],
    static_findings: list[RawStaticFinding],
) -> list[str]:
    """Infer risk tags from URL patterns and request/response data.

    Risk tags:
    - login: path contains /auth, /login, /signin, /token, or response sets cookie/bearer
    - payment: path has /pay, /charge, /order, /checkout, or body has amount/price/card
    - 2fa: path contains /otp, /verify, /mfa
    - device_binding: request has Android ID, build fingerprint, or advertising ID
    - captcha: response body contains captcha/recaptcha/hcaptcha keys
    """
    tags: set[str] = set()
    url_lower = url_template.lower()

    # Login detection
    login_patterns = ["/auth", "/login", "/signin", "/sign-in", "/token", "/oauth", "/session"]
    if any(p in url_lower for p in login_patterns):
        tags.add("login")

    # Check if response sets auth tokens
    for trace in trace_records:
        if trace.response_headers:
            for key in trace.response_headers:
                if key.lower() in ("set-cookie", "authorization"):
                    tags.add("login")
                    break

        # Check response body for token patterns
        if trace.response_body_parsed and isinstance(trace.response_body_parsed, dict):
            body_keys = {k.lower() for k in trace.response_body_parsed.keys()}
            if body_keys & {"token", "access_token", "refresh_token", "id_token", "jwt"}:
                tags.add("login")

    # Payment detection
    payment_patterns = ["/pay", "/charge", "/order", "/checkout", "/billing", "/purchase"]
    if any(p in url_lower for p in payment_patterns):
        tags.add("payment")

    for trace in trace_records:
        if trace.request_body_parsed and isinstance(trace.request_body_parsed, dict):
            body_keys = {k.lower() for k in trace.request_body_parsed.keys()}
            if body_keys & {"amount", "price", "card_number", "card", "payment_method", "cvv"}:
                tags.add("payment")

    # 2FA detection
    twofa_patterns = ["/otp", "/verify", "/mfa", "/two-factor", "/2fa", "/totp"]
    if any(p in url_lower for p in twofa_patterns):
        tags.add("2fa")

    # Device binding detection
    device_binding_headers = {"x-device-id", "x-android-id", "x-advertising-id"}
    for trace in trace_records:
        header_keys_lower = {k.lower() for k in trace.request_headers.keys()}
        if header_keys_lower & device_binding_headers:
            tags.add("device_binding")

        if trace.request_body_parsed and isinstance(trace.request_body_parsed, dict):
            body_keys = {k.lower() for k in trace.request_body_parsed.keys()}
            if body_keys & {"android_id", "device_id", "advertising_id", "build_fingerprint"}:
                tags.add("device_binding")

    # Captcha detection
    for trace in trace_records:
        if trace.response_body_parsed and isinstance(trace.response_body_parsed, dict):
            body_str = str(trace.response_body_parsed).lower()
            if any(kw in body_str for kw in ["captcha", "recaptcha", "hcaptcha"]):
                tags.add("captcha")

    return sorted(tags)


def infer_auth_requirements(trace_records: list[TraceRecord]) -> list[AuthType]:
    """Infer auth requirements from observed request headers."""
    auth_types: set[AuthType] = set()

    for trace in trace_records:
        auth_header = trace.request_headers.get(
            "Authorization", trace.request_headers.get("authorization", "")
        )

        if auth_header:
            if auth_header.startswith("Bearer "):
                auth_types.add(AuthType.BEARER)
            elif auth_header.startswith("Basic "):
                auth_types.add(AuthType.BASIC)
            else:
                auth_types.add(AuthType.BEARER)  # Default to bearer

        # Check for API key headers
        for key in trace.request_headers:
            if key.lower() in ("x-api-key", "api-key", "apikey"):
                auth_types.add(AuthType.APIKEY)

        # Check for cookies
        if "Cookie" in trace.request_headers or "cookie" in trace.request_headers:
            auth_types.add(AuthType.COOKIE)

    if not auth_types:
        auth_types.add(AuthType.NONE)

    return sorted(auth_types, key=lambda a: a.value)


def infer_pagination(
    url_template: str,
    trace_records: list[TraceRecord],
    params: list[ParamSchema],
) -> tuple[Optional[bool], Optional[str]]:
    """Infer whether an endpoint is paginated and what pattern it uses."""
    url_lower = url_template.lower()
    param_names = {p.name.lower() for p in params}

    # Check URL and params for pagination patterns
    if "cursor" in param_names or "cursor" in url_lower:
        return True, "cursor"

    if "offset" in param_names or "limit" in param_names:
        return True, "offset"

    if "page" in param_names or "page_size" in param_names or "per_page" in param_names:
        return True, "page"

    # Check response bodies for pagination metadata
    for trace in trace_records:
        if trace.response_body_parsed and isinstance(trace.response_body_parsed, dict):
            body_keys = {k.lower() for k in trace.response_body_parsed.keys()}

            if "next_cursor" in body_keys or "cursor" in body_keys:
                return True, "cursor"
            if "total_pages" in body_keys or "next_page" in body_keys:
                return True, "page"
            if body_keys & {"total", "count", "total_count"} and body_keys & {"offset", "limit"}:
                return True, "offset"

    return None, None


def infer_idempotency(method: str) -> Optional[bool]:
    """Infer idempotency based on HTTP method.

    GET, PUT, DELETE, HEAD are idempotent.
    POST, PATCH are not idempotent by default.
    """
    idempotent_methods = {"GET", "PUT", "DELETE", "HEAD"}
    non_idempotent_methods = {"POST", "PATCH"}

    if method.upper() in idempotent_methods:
        return True
    elif method.upper() in non_idempotent_methods:
        return False
    return None
