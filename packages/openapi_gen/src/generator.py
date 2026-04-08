"""OpenAPI 3.1 Spec Generator — ActionCatalog → OpenAPI document.

Generates a valid OpenAPI 3.1 specification from an ActionCatalog.
Only includes actions that are approved and above the confidence threshold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject, AuthType


@dataclass
class OpenAPIGenConfig:
    """Configuration for OpenAPI generation."""

    gateway_base_url: str = "http://localhost:8080"
    min_confidence: float = 0.6
    include_unapproved: bool = False
    title_prefix: str = "Gateway API"


def generate_openapi(
    catalog: ActionCatalog,
    config: Optional[OpenAPIGenConfig] = None,
) -> dict:
    """Generate an OpenAPI 3.1 spec from an ActionCatalog.

    Only actions with approved=True and confidence >= min_confidence
    are included by default.
    """
    config = config or OpenAPIGenConfig()

    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{config.title_prefix} — {catalog.package_name} {catalog.version_name}",
            "version": catalog.version_name,
            "description": (
                f"Auto-generated API gateway for {catalog.package_name}. "
                f"Contains {catalog.total_actions} discovered actions."
            ),
        },
        "servers": [{"url": config.gateway_base_url}],
        "paths": {},
        "components": {
            "securitySchemes": {},
            "schemas": {},
        },
    }

    # Track security schemes needed
    security_schemes: set[str] = set()

    for action in catalog.actions:
        # Apply filters
        if not config.include_unapproved and not action.approved:
            continue
        if action.confidence_score < config.min_confidence:
            continue

        # Build path
        path = f"/apps/{catalog.app_id}/actions/{action.action_id}/execute"
        path_item = _build_path_item(action, catalog)
        spec["paths"][path] = path_item

        # Collect security schemes
        for auth in action.auth_requirements:
            if auth != AuthType.NONE:
                security_schemes.add(auth.value)

    # Build security schemes
    spec["components"]["securitySchemes"] = _build_security_schemes(security_schemes)

    # Add catalog inspection endpoints
    spec["paths"][f"/apps/{catalog.app_id}"] = {
        "get": {
            "summary": f"Get metadata for {catalog.package_name}",
            "operationId": f"getApp_{catalog.app_id}",
            "responses": {
                "200": {
                    "description": "App metadata",
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            },
        }
    }

    spec["paths"][f"/apps/{catalog.app_id}/actions"] = {
        "get": {
            "summary": "List all discovered actions",
            "operationId": f"listActions_{catalog.app_id}",
            "parameters": [
                {
                    "name": "confidence_min",
                    "in": "query",
                    "schema": {"type": "number"},
                    "description": "Minimum confidence score filter",
                },
                {
                    "name": "approved_only",
                    "in": "query",
                    "schema": {"type": "boolean"},
                    "description": "Only return approved actions",
                },
            ],
            "responses": {
                "200": {
                    "description": "List of actions",
                    "content": {"application/json": {"schema": {"type": "array"}}},
                }
            },
        }
    }

    return spec


def generate_openapi_json(
    catalog: ActionCatalog,
    config: Optional[OpenAPIGenConfig] = None,
    indent: int = 2,
) -> str:
    """Generate OpenAPI spec as JSON string."""
    spec = generate_openapi(catalog, config)
    return json.dumps(spec, indent=indent)


def generate_openapi_yaml(
    catalog: ActionCatalog,
    config: Optional[OpenAPIGenConfig] = None,
) -> str:
    """Generate OpenAPI spec as YAML string."""
    spec = generate_openapi(catalog, config)
    return yaml.dump(spec, default_flow_style=False, sort_keys=False)


def _build_path_item(action: ActionObject, catalog: ActionCatalog) -> dict:
    """Build an OpenAPI PathItem from an ActionObject."""
    operation: dict[str, Any] = {
        "summary": f"{action.method} {action.url_template}",
        "operationId": f"execute_{action.action_id.replace('-', '_')}",
        "description": (
            f"Execute action against {action.base_url}{action.url_template}\n"
            f"Source: {action.source} | Confidence: {action.confidence_score}"
        ),
        "tags": [action.base_url or catalog.package_name],
        "x-risk-tags": action.risk_tags,
        "x-confidence": action.confidence_score,
        "x-source": action.source,
        "x-original-method": action.method,
        "x-original-url": f"{action.base_url}{action.url_template}",
    }

    # Build parameters
    parameters = []
    body_params = []

    for param in action.params:
        if param.location == "body":
            body_params.append(param)
            continue

        param_spec: dict[str, Any] = {
            "name": param.name,
            "in": param.location,
            "required": param.required,
            "schema": {"type": param.type},
        }
        if param.description:
            param_spec["description"] = param.description
        if param.example:
            param_spec["example"] = param.example

        parameters.append(param_spec)

    if parameters:
        operation["parameters"] = parameters

    # Build request body from body params
    if body_params:
        properties = {}
        required_props = []
        for bp in body_params:
            properties[bp.name] = {"type": bp.type}
            if bp.description:
                properties[bp.name]["description"] = bp.description
            if bp.required:
                required_props.append(bp.name)

        operation["requestBody"] = {
            "required": bool(required_props),
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        **({"required": required_props} if required_props else {}),
                    }
                }
            },
        }

    # Build security requirement
    if action.auth_requirements:
        security = []
        for auth in action.auth_requirements:
            if auth == AuthType.BEARER:
                security.append({"bearerAuth": []})
            elif auth == AuthType.BASIC:
                security.append({"basicAuth": []})
            elif auth == AuthType.APIKEY:
                security.append({"apiKeyAuth": []})
            elif auth == AuthType.COOKIE:
                security.append({"cookieAuth": []})

        if security:
            operation["security"] = security

    # Build responses
    operation["responses"] = {
        "200": {
            "description": "Successful execution",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        "400": {"description": "Invalid parameters"},
        "401": {"description": "Authentication required"},
        "500": {"description": "Execution error"},
    }

    return {"post": operation}


def _build_security_schemes(schemes: set[str]) -> dict:
    """Build OpenAPI security scheme components."""
    result = {}

    if "bearer" in schemes:
        result["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    if "basic" in schemes:
        result["basicAuth"] = {
            "type": "http",
            "scheme": "basic",
        }
    if "apikey" in schemes:
        result["apiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }
    if "cookie" in schemes:
        result["cookieAuth"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "session",
        }

    return result
