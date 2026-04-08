"""TraceRecord — Layer 3 output schema.

Emitted by the dynamic analyzer for every observed network request.
Frida hooks populate all mandatory fields; optional fields are filled by post-processing.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TraceRecord(BaseModel):
    """A single observed network request captured at runtime.

    Produced by Frida hooks and post-processed with UI context correlation.
    """

    # Identity
    trace_id: str = Field(description="UUID for this trace record")
    app_id: str
    session_id: str = Field(description="One session per emulator run")
    timestamp_ms: int

    # Request
    method: str
    url: str = Field(description="Full URL as observed")
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body_raw: Optional[bytes] = None
    request_body_parsed: Optional[dict] = None

    # Response
    response_status: Optional[int] = None
    response_headers: Optional[dict[str, str]] = None
    response_body_raw: Optional[bytes] = None
    response_body_parsed: Optional[dict] = None
    response_time_ms: Optional[int] = None

    # UI context captured at the moment of the request
    ui_activity: Optional[str] = None
    ui_fragment: Optional[str] = None
    ui_event_type: Optional[str] = Field(
        default=None,
        description='"click", "scroll", "system", "background"',
    )
    ui_element_id: Optional[str] = None

    # Code context from Frida stack trace
    call_stack: list[str] = Field(default_factory=list)
    invoking_class: Optional[str] = None
    invoking_method: Optional[str] = None

    # TLS status
    tls_intercepted: bool = False
    pinning_bypassed: bool = False

    class Config:
        # Allow bytes fields to serialize
        json_encoders = {bytes: lambda v: v.hex() if v else None}
