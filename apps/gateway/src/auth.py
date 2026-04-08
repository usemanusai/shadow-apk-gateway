"""API Authentication middleware for the gateway."""

from __future__ import annotations

from typing import Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    """Optional API key authentication for gateway access.

    When api_key is set, all requests must include a valid
    X-Gateway-Key header or API-Key query parameter.
    """

    def __init__(self, app, api_key: Optional[str] = None):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if self.api_key:
            # Check header
            provided_key = request.headers.get("X-Gateway-Key", "")
            if not provided_key:
                # Check query param
                provided_key = request.query_params.get("api_key", "")

            if provided_key != self.api_key:
                raise HTTPException(401, "Invalid or missing API key")

        return await call_next(request)
