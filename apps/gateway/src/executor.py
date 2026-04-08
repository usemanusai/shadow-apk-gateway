"""Executor — Translates ActionObject executions into live HTTP requests.

Validates parameters, templates URLs, attaches auth, and logs results.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from packages.core_schema.models.action_object import ActionObject


@dataclass
class ExecutionRequest:
    """Request to execute an action."""

    action: ActionObject
    params: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"
    timeout: float = 30.0
    retries: int = 1


@dataclass
class ExecutionResult:
    """Result of an action execution."""

    correlation_id: str
    status_code: int
    headers: dict[str, str]
    body: Any
    latency_ms: int
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "correlation_id": self.correlation_id,
            "status_code": self.status_code,
            "headers": self.headers,
            "body": self.body,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


class ExecutionError(Exception):
    """Raised when action execution fails."""


class Executor:
    """Executes ActionObjects as live HTTP requests.

    Handles URL templating, parameter validation, auth attachment,
    timeout/retry, and result normalization.
    """

    def __init__(self, default_timeout: float = 30.0, max_retries: int = 2):
        self.default_timeout = default_timeout
        self.max_retries = max_retries

    async def execute(
        self,
        request: ExecutionRequest,
        session: Optional[dict] = None,
    ) -> ExecutionResult:
        """Execute an action request and return the result."""
        correlation_id = str(uuid.uuid4())
        action = request.action
        start_time = time.monotonic()

        # Validate parameters
        validation_error = self._validate_params(action, request.params)
        if validation_error:
            return ExecutionResult(
                correlation_id=correlation_id,
                status_code=400,
                headers={},
                body={"error": validation_error},
                latency_ms=0,
                error=validation_error,
            )

        # Build URL
        url = self._build_url(action, request.params)

        # Build headers
        headers = self._build_headers(action, request.params, session)

        # Build query params
        query_params = self._build_query_params(action, request.params)

        # Build body
        body = self._build_body(action, request.params)

        # Execute with retries
        last_error: Optional[str] = None
        for attempt in range(max(request.retries, 1)):
            try:
                async with httpx.AsyncClient(timeout=request.timeout, follow_redirects=True) as client:
                    response = await client.request(
                        method=action.method,
                        url=url,
                        headers=headers,
                        params=query_params,
                        json=body if body else None,
                    )

                latency_ms = int((time.monotonic() - start_time) * 1000)

                # Parse response body
                resp_body: Any = None
                try:
                    resp_body = response.json()
                except Exception:
                    resp_body = response.text

                return ExecutionResult(
                    correlation_id=correlation_id,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body=resp_body,
                    latency_ms=latency_ms,
                )

            except httpx.TimeoutException:
                last_error = f"Request timed out after {request.timeout}s"
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
            except Exception as e:
                last_error = f"Execution error: {e}"

        latency_ms = int((time.monotonic() - start_time) * 1000)
        return ExecutionResult(
            correlation_id=correlation_id,
            status_code=502,
            headers={},
            body={"error": last_error},
            latency_ms=latency_ms,
            error=last_error,
        )

    def _validate_params(self, action: ActionObject, params: dict) -> Optional[str]:
        """Validate caller-supplied params against action's param schema."""
        for param in action.params:
            if param.required and param.name not in params:
                return f"Missing required parameter: {param.name}"
        return None

    def _build_url(self, action: ActionObject, params: dict) -> str:
        """Build the full URL from base_url + url_template with path params."""
        url = f"{action.base_url}{action.url_template}"

        # Substitute path parameters
        for param in action.params:
            if param.location == "path" and param.name in params:
                url = url.replace(f"{{{param.name}}}", str(params[param.name]))

        return url

    def _build_headers(
        self,
        action: ActionObject,
        params: dict,
        session: Optional[dict] = None,
    ) -> dict[str, str]:
        """Build request headers from action params and session."""
        headers: dict[str, str] = {}

        # Add header params
        for param in action.params:
            if param.location == "header" and param.name in params:
                headers[param.name] = str(params[param.name])

        # Attach session auth
        if session:
            if "Authorization" in session:
                headers["Authorization"] = session["Authorization"]
            if "cookies" in session:
                headers["Cookie"] = session["cookies"]

        return headers

    def _build_query_params(self, action: ActionObject, params: dict) -> dict[str, str]:
        """Build query parameters."""
        query: dict[str, str] = {}
        for param in action.params:
            if param.location == "query" and param.name in params:
                query[param.name] = str(params[param.name])
        return query

    def _build_body(self, action: ActionObject, params: dict) -> Optional[dict]:
        """Build request body from body params."""
        body_params = [p for p in action.params if p.location == "body"]
        if not body_params:
            return None

        body: dict[str, Any] = {}
        for param in body_params:
            if param.name in params:
                body[param.name] = params[param.name]

        return body if body else None
