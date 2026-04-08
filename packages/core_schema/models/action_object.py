"""ActionObject — Central model flowing from Layer 4 (Normalization) to Layer 5 (Gateway).

Every field that the gateway uses to execute a request must be present and validated here.
Downstream code must never accept a raw endpoint string.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AuthType(str, Enum):
    """Authentication mechanisms an endpoint may require."""

    NONE = "none"
    BEARER = "bearer"
    BASIC = "basic"
    COOKIE = "cookie"
    APIKEY = "apikey"
    OAUTH2 = "oauth2"
    DEVICE_BOUND = "device_bound"


class ParamSchema(BaseModel):
    """Schema for a single parameter of an API action."""

    name: str
    location: Literal["path", "query", "header", "body", "cookie"]
    required: bool
    type: str = Field(description="JSON schema type: string, number, boolean, object, array")
    example: Optional[str] = None
    description: Optional[str] = None
    sensitive: bool = Field(
        default=False,
        description="True for tokens, passwords, device IDs — masked in audit logs",
    )


class EvidenceRef(BaseModel):
    """Reference to evidence supporting the existence of an action."""

    source_type: Literal["smali", "har", "pcap", "jsasset", "frida_trace"]
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    timestamp_ms: Optional[int] = None
    ui_activity: Optional[str] = None
    ui_event: Optional[str] = None


class ActionObject(BaseModel):
    """A single executable API action discovered from an Android application.

    Represents a normalized, validated API endpoint with all metadata needed
    for the gateway to execute it.
    """

    # Identity
    action_id: str = Field(description="Stable UUID, deterministic from host+path+method")
    source: Literal["static", "dynamic", "merged"]
    app_id: str
    package_name: str
    version_name: str
    version_code: int

    # HTTP specification
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    url_template: str = Field(description="RFC 6570-style template: /users/{user_id}/profile")
    base_url: str = Field(description="e.g., https://api.example.com")
    params: list[ParamSchema] = Field(default_factory=list)

    # Auth and dependencies
    auth_requirements: list[AuthType] = Field(default_factory=list)
    session_dependencies: list[str] = Field(
        default_factory=list,
        description="action_ids that must be executed first",
    )
    preconditions: list[str] = Field(
        default_factory=list,
        description="Human-readable precondition descriptions",
    )

    # Quality signals
    confidence_score: float = Field(ge=0.0, le=1.0, description="0.0–1.0 confidence")
    evidence: list[EvidenceRef] = Field(default_factory=list)
    risk_tags: list[str] = Field(
        default_factory=list,
        description='Tags: "login","payment","2fa","captcha","device_binding"',
    )

    # Behavioral metadata
    is_idempotent: Optional[bool] = None
    is_paginated: Optional[bool] = None
    pagination_pattern: Optional[str] = Field(
        default=None,
        description='"cursor", "offset", "page"',
    )

    # Review workflow
    approved: bool = False
    approved_by: Optional[str] = None
    notes: Optional[str] = None
