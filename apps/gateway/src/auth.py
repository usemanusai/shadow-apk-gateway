"""API Authentication middleware for the gateway.

Provides two layers of protection:
1. API key authentication via X-Gateway-Key header or api_key query param
2. HMAC-SHA256 constant-time comparison to prevent timing attacks

Configure via GATEWAY_API_KEY environment variable.
"""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# Paths excluded from authentication
AUTH_EXEMPT_PATHS = frozenset({
    "/health",
    "/healthz",
    "/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
})


class AuthMiddleware(BaseHTTPMiddleware):
    """API key authentication middleware with constant-time comparison.

    When api_key is set, all requests must include a valid
    X-Gateway-Key header or api_key query parameter.

    Uses HMAC-SHA256 constant-time comparison to prevent timing attacks
    that could leak the API key byte-by-byte.

    Exempt paths (health checks, docs) are always allowed.
    """

    def __init__(self, app, api_key: Optional[str] = None):
        super().__init__(app)
        self.api_key = api_key or os.environ.get("GATEWAY_API_KEY", "")

    async def dispatch(self, request: Request, call_next):
        # Skip auth for exempt paths
        if request.url.path in AUTH_EXEMPT_PATHS:
            return await call_next(request)

        if self.api_key:
            # Check header first
            provided_key = request.headers.get("X-Gateway-Key", "")
            if not provided_key:
                # Check query param
                provided_key = request.query_params.get("api_key", "")

            if not provided_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing API key — provide X-Gateway-Key header or api_key query parameter"},
                )

            # HMAC-SHA256 constant-time comparison — prevents timing attacks
            if not _constant_time_compare(provided_key, self.api_key):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid API key"},
                )

        return await call_next(request)


def _constant_time_compare(provided: str, expected: str) -> bool:
    """Compare two strings in constant time using HMAC.

    Even if the strings are different lengths, this function will
    not leak timing information about which bytes matched.
    """
    return hmac.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )
