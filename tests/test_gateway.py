"""Tests for the Gateway executor and rate limiter."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from apps.gateway.src.executor import Executor, ExecutionRequest, ExecutionResult
from apps.gateway.src.rate_limit import RateLimiter
from apps.gateway.src.audit import AuditLogger
from packages.core_schema.models.action_object import ActionObject, AuthType, ParamSchema


def _make_action(
    method: str = "GET",
    url_template: str = "/api/users",
    base_url: str = "https://api.example.com",
    params: list[ParamSchema] | None = None,
) -> ActionObject:
    return ActionObject(
        action_id="test-action",
        source="static",
        app_id="test",
        package_name="com.example",
        version_name="1.0",
        version_code=1,
        method=method,
        url_template=url_template,
        base_url=base_url,
        params=params or [],
        auth_requirements=[AuthType.NONE],
        confidence_score=0.80,
    )


class TestExecutor:
    """Test the action executor."""

    def test_validate_missing_required_param(self):
        executor = Executor()
        action = _make_action(params=[
            ParamSchema(name="id", location="path", required=True, type="integer"),
        ])
        error = executor._validate_params(action, {})
        assert error is not None
        assert "id" in error

    def test_validate_passes_with_required_param(self):
        executor = Executor()
        action = _make_action(params=[
            ParamSchema(name="id", location="path", required=True, type="integer"),
        ])
        error = executor._validate_params(action, {"id": 123})
        assert error is None

    def test_build_url(self):
        executor = Executor()
        action = _make_action(
            url_template="/api/users/{id}",
            params=[ParamSchema(name="id", location="path", required=True, type="integer")],
        )
        url = executor._build_url(action, {"id": 42})
        assert url == "https://api.example.com/api/users/42"

    def test_build_query_params(self):
        executor = Executor()
        action = _make_action(params=[
            ParamSchema(name="page", location="query", required=False, type="integer"),
            ParamSchema(name="limit", location="query", required=False, type="integer"),
        ])
        query = executor._build_query_params(action, {"page": 1, "limit": 20})
        assert query == {"page": "1", "limit": "20"}

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.request")
    async def test_execute_success(self, mock_request):
        """Test full successful execution with httpx."""
        mock_response = httpx.Response(
            status_code=200, 
            json={"status": "ok"}, 
            headers={"X-Test": "Passed"},
            request=httpx.Request("POST", "https://api.example.com")
        )
        mock_request.return_value = mock_response

        executor = Executor()
        action = _make_action(
            method="POST",
            url_template="/api/test",
            params=[ParamSchema(name="Auth", location="header", required=True, type="string")]
        )
        
        request = ExecutionRequest(
            action=action, 
            params={"Auth": "Bearer xyz"},
            timeout=5.0
        )
        
        result = await executor.execute(request)
        
        assert result.status_code == 200
        assert result.body == {"status": "ok"}
        
        # Verify httpx was called correctly
        mock_request.assert_called_once()
        kwargs = mock_request.call_args.kwargs
        assert kwargs["method"] == "POST"
        assert kwargs["url"] == "https://api.example.com/api/test"
        assert kwargs["headers"] == {"Auth": "Bearer xyz"}

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.request")
    async def test_execute_timeout_retries(self, mock_request):
        """Test executor correctly retries on timeout."""
        mock_request.side_effect = httpx.TimeoutException("Timeout")
        
        executor = Executor()
        action = _make_action(method="GET", url_template="/timeout")
        
        request = ExecutionRequest(action=action, retries=2)
        result = await executor.execute(request)
        
        # Should gracefully fail after retries
        assert result.status_code == 502
        assert mock_request.call_count == 2
        assert "timed out" in result.error


class TestRateLimiter:
    """Test the rate limiter."""

    def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            limiter.check("app1", "action1")  # Should not raise

    def test_blocks_over_limit(self):
        from fastapi import HTTPException
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.check("app1", "action1")

        with pytest.raises(HTTPException) as exc_info:
            limiter.check("app1", "action1")
        assert exc_info.value.status_code == 429

    def test_reset(self):
        from fastapi import HTTPException
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        limiter.check("app1", "action1")

        with pytest.raises(HTTPException):
            limiter.check("app1", "action1")

        limiter.reset("app1")
        limiter.check("app1", "action1")  # Should work again


class TestAuditLogger:
    """Test the audit logger."""

    def test_logs_execution(self):
        logger = AuditLogger()
        entry = logger.log_execution(
            app_id="test_app",
            action_id="action_1",
            tenant_id="default",
            request_url="https://api.example.com/users?token=secret",
            response_status=200,
            latency_ms=150,
            sensitive_params=["token"],
        )

        assert entry["response_status"] == 200
        assert "secret" not in entry["request_url"]
        assert "***REDACTED***" in entry["request_url"]

    def test_query_entries(self):
        logger = AuditLogger()
        logger.log_execution("app1", "action1", "t1", "/url", 200, 100)
        logger.log_execution("app2", "action2", "t1", "/url", 404, 200)

        entries = logger.get_entries(app_id="app1")
        assert len(entries) == 1
