"""Request/response capture — Frida message stream → TraceRecord pipeline.

Connects to the Frida message stream, parses emitted JSON events,
constructs TraceRecord objects, and stores them.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from packages.core_schema.models.trace_record import TraceRecord


class CaptureError(Exception):
    """Raised when capture operations fail."""


class CaptureSession:
    """Captures network trace records from Frida hook messages.

    Receives JSON messages from Frida scripts, validates them,
    and converts them to TraceRecord instances.
    """

    def __init__(self, app_id: str, session_id: Optional[str] = None):
        self.app_id = app_id
        self.session_id = session_id or str(uuid.uuid4())
        self.records: list[TraceRecord] = []
        self._raw_events: list[dict] = []

    def on_frida_message(self, message: dict, data: Optional[bytes] = None) -> None:
        """Handle a message from a Frida script.

        This is the callback passed to frida_runner.run_script(on_message=...).
        """
        if message.get("type") != "send":
            # Log error messages
            if message.get("type") == "error":
                print(f"[Frida Error] {message.get('description', 'unknown')}")
            return

        payload = message.get("payload")
        if not isinstance(payload, dict):
            return

        self._raw_events.append(payload)

        try:
            record = self._payload_to_trace_record(payload)
            self.records.append(record)
        except Exception as e:
            print(f"[Capture] Failed to parse event: {e}")

    def process_events_from_file(self, events_file: str) -> list[TraceRecord]:
        """Process pre-recorded Frida events from a JSON file.

        Useful for testing without a live emulator.
        """
        with open(events_file, "r") as f:
            events = json.load(f)

        for event in events:
            self._raw_events.append(event)
            try:
                record = self._payload_to_trace_record(event)
                self.records.append(record)
            except Exception as e:
                print(f"[Capture] Failed to parse event: {e}")

        return self.records

    def process_events(self, events: list[dict]) -> list[TraceRecord]:
        """Process a list of Frida event payloads."""
        for event in events:
            self._raw_events.append(event)
            try:
                record = self._payload_to_trace_record(event)
                self.records.append(record)
            except Exception as e:
                print(f"[Capture] Failed to parse event: {e}")

        return self.records

    def _payload_to_trace_record(self, payload: dict) -> TraceRecord:
        """Convert a Frida hook payload to a TraceRecord."""
        # Extract request data
        method = payload.get("method", "GET").upper()
        url = payload.get("url", "")
        if not url:
            raise ValueError("Missing 'url' in Frida event payload")

        # Parse headers
        request_headers = payload.get("requestHeaders", {})
        if isinstance(request_headers, str):
            try:
                request_headers = json.loads(request_headers)
            except json.JSONDecodeError:
                request_headers = {}

        # Parse request body
        request_body_raw = None
        request_body_parsed = None
        body_text = payload.get("requestBodyText") or payload.get("requestBody")
        if body_text:
            if isinstance(body_text, str):
                request_body_raw = body_text.encode("utf-8", errors="replace")
                try:
                    request_body_parsed = json.loads(body_text)
                except (json.JSONDecodeError, ValueError):
                    pass
            elif isinstance(body_text, bytes):
                request_body_raw = body_text

        # Parse response data
        response_status = payload.get("responseStatus") or payload.get("status")
        if response_status is not None:
            try:
                response_status = int(response_status)
            except (ValueError, TypeError):
                response_status = None

        response_headers = payload.get("responseHeaders", {})
        if isinstance(response_headers, str):
            try:
                response_headers = json.loads(response_headers)
            except json.JSONDecodeError:
                response_headers = {}

        response_body_raw = None
        response_body_parsed = None
        resp_text = payload.get("responseBodyText") or payload.get("responseBody")
        if resp_text:
            if isinstance(resp_text, str):
                response_body_raw = resp_text.encode("utf-8", errors="replace")
                try:
                    response_body_parsed = json.loads(resp_text)
                except (json.JSONDecodeError, ValueError):
                    pass

        response_time_ms = payload.get("responseTimeMs") or payload.get("duration")
        if response_time_ms is not None:
            try:
                response_time_ms = int(response_time_ms)
            except (ValueError, TypeError):
                response_time_ms = None

        # UI context
        ui_activity = payload.get("uiActivity") or payload.get("activity")
        ui_fragment = payload.get("uiFragment") or payload.get("fragment")
        ui_event_type = payload.get("uiEventType") or payload.get("eventType")
        ui_element_id = payload.get("uiElementId") or payload.get("elementId")

        # Code context
        call_stack = payload.get("callStack", [])
        if isinstance(call_stack, str):
            call_stack = call_stack.split("\n")
        invoking_class = payload.get("invokingClass") or payload.get("className")
        invoking_method = payload.get("invokingMethod") or payload.get("methodName")

        # TLS
        tls_intercepted = payload.get("tlsIntercepted", False)
        pinning_bypassed = payload.get("pinningBypassed", False)

        timestamp_ms = payload.get("timestampMs") or payload.get("timestamp")
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        else:
            timestamp_ms = int(timestamp_ms)

        return TraceRecord(
            trace_id=str(uuid.uuid4()),
            app_id=self.app_id,
            session_id=self.session_id,
            timestamp_ms=timestamp_ms,
            method=method,
            url=url,
            request_headers=request_headers,
            request_body_raw=request_body_raw,
            request_body_parsed=request_body_parsed,
            response_status=response_status,
            response_headers=response_headers,
            response_body_raw=response_body_raw,
            response_body_parsed=response_body_parsed,
            response_time_ms=response_time_ms,
            ui_activity=ui_activity,
            ui_fragment=ui_fragment,
            ui_event_type=ui_event_type,
            ui_element_id=ui_element_id,
            call_stack=call_stack,
            invoking_class=invoking_class,
            invoking_method=invoking_method,
            tls_intercepted=tls_intercepted,
            pinning_bypassed=pinning_bypassed,
        )

    def get_records(self) -> list[TraceRecord]:
        """Return all captured trace records."""
        return list(self.records)

    def get_records_json(self) -> list[dict]:
        """Return all trace records as JSON-serializable dicts."""
        return [r.model_dump(mode="json") for r in self.records]

    def clear(self) -> None:
        """Clear all captured records."""
        self.records.clear()
        self._raw_events.clear()
