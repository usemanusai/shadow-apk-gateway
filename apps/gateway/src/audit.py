"""Audit Logger — Structured JSON audit logging for action executions.

Writes one JSON line per execution to a configurable log file.
Masks sensitive fields to prevent credential leakage.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional


REDACTED = "***REDACTED***"


class AuditLogger:
    """Structured audit logger for gateway action executions.

    Writes JSON-lines (JSONL) to a configurable log file.
    All sensitive parameter values are masked in the output.
    """

    def __init__(self, log_path: Optional[str | Path] = None):
        self.log_path = Path(log_path) if log_path else None
        self._entries: list[dict] = []  # In-memory for testing

    def log_execution(
        self,
        app_id: str,
        action_id: str,
        tenant_id: str,
        request_url: str,
        response_status: int,
        latency_ms: int,
        error: Optional[str] = None,
        sensitive_params: Optional[list[str]] = None,
    ) -> dict:
        """Log an action execution event.

        Sensitive parameter names are recorded but their values in the
        URL are masked with ***REDACTED***.
        """
        correlation_id = str(uuid.uuid4())

        # Mask sensitive values in the URL
        masked_url = request_url
        if sensitive_params:
            for param_name in sensitive_params:
                # Mask query param values
                import re
                masked_url = re.sub(
                    rf'({re.escape(param_name)}=)[^&]*',
                    rf'\1{REDACTED}',
                    masked_url,
                )

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "timestamp_ms": int(time.time() * 1000),
            "correlation_id": correlation_id,
            "app_id": app_id,
            "action_id": action_id,
            "tenant_id": tenant_id,
            "request_url": masked_url,
            "response_status": response_status,
            "latency_ms": latency_ms,
            "error": error,
        }

        # Store in memory
        self._entries.append(entry)

        # Write to file if configured
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

        return entry

    def get_entries(
        self,
        app_id: Optional[str] = None,
        action_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve audit log entries with optional filters."""
        entries = self._entries

        if app_id:
            entries = [e for e in entries if e.get("app_id") == app_id]
        if action_id:
            entries = [e for e in entries if e.get("action_id") == action_id]

        return entries[-limit:]

    def clear(self) -> None:
        """Clear in-memory entries."""
        self._entries.clear()
