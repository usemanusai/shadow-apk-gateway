"""Tests for OpenAPI spec generation."""

import json
import pytest

from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject, AuthType, ParamSchema
from packages.openapi_gen.src.generator import generate_openapi, OpenAPIGenConfig


def _make_test_catalog() -> ActionCatalog:
    """Create a test ActionCatalog."""
    action1 = ActionObject(
        action_id="test-action-001",
        source="merged",
        app_id="test123",
        package_name="com.example.test",
        version_name="1.0.0",
        version_code=1,
        method="GET",
        url_template="/api/v1/users/{id}",
        base_url="https://api.example.com",
        params=[
            ParamSchema(name="id", location="path", required=True, type="integer"),
            ParamSchema(name="fields", location="query", required=False, type="string"),
        ],
        auth_requirements=[AuthType.BEARER],
        confidence_score=0.85,
        approved=True,
    )

    action2 = ActionObject(
        action_id="test-action-002",
        source="static",
        app_id="test123",
        package_name="com.example.test",
        version_name="1.0.0",
        version_code=1,
        method="POST",
        url_template="/api/v1/login",
        base_url="https://api.example.com",
        params=[
            ParamSchema(name="email", location="body", required=True, type="string"),
            ParamSchema(name="password", location="body", required=True, type="string", sensitive=True),
        ],
        auth_requirements=[AuthType.NONE],
        confidence_score=0.70,
        risk_tags=["login"],
        approved=True,
    )

    return ActionCatalog(
        app_id="test123",
        package_name="com.example.test",
        version_name="1.0.0",
        version_code=1,
        actions=[action1, action2],
    )


class TestOpenAPIGenerator:
    """Test OpenAPI 3.1 spec generation."""

    def test_generates_valid_structure(self):
        catalog = _make_test_catalog()
        spec = generate_openapi(catalog)

        assert spec["openapi"] == "3.1.0"
        assert "info" in spec
        assert "paths" in spec
        assert "components" in spec

    def test_includes_approved_actions(self):
        catalog = _make_test_catalog()
        spec = generate_openapi(catalog)

        # Should have action paths + catalog endpoints
        assert len(spec["paths"]) >= 2

    def test_respects_confidence_filter(self):
        catalog = _make_test_catalog()
        config = OpenAPIGenConfig(min_confidence=0.80)
        spec = generate_openapi(catalog, config)

        # Only the 0.85 action should be included, plus catalog endpoints
        action_paths = [p for p in spec["paths"] if "execute" in p]
        assert len(action_paths) == 1

    def test_security_schemes(self):
        catalog = _make_test_catalog()
        spec = generate_openapi(catalog)

        schemes = spec["components"]["securitySchemes"]
        assert "bearerAuth" in schemes

    def test_request_body_for_post(self):
        catalog = _make_test_catalog()
        config = OpenAPIGenConfig(min_confidence=0.0)
        spec = generate_openapi(catalog, config)

        # Find the login action path
        login_paths = [
            p for p in spec["paths"]
            if "test-action-002" in p
        ]
        assert len(login_paths) == 1

        login_op = spec["paths"][login_paths[0]]["post"]
        assert "requestBody" in login_op
