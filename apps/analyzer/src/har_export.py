"""HAR Export — Convert TraceStore data to HAR 1.2 format.

Produces valid HAR (HTTP Archive) documents for replay and inspection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse

from packages.core_schema.models.trace_record import TraceRecord


def export_har(records: list[TraceRecord], creator_name: str = "Shadow-APK-Gateway") -> dict:
    """Convert a list of TraceRecords to a HAR 1.2 document.

    Args:
        records: List of TraceRecords to export.
        creator_name: Name of the tool creating the HAR.

    Returns:
        A HAR 1.2 compliant dictionary.
    """
    entries = [_record_to_har_entry(r) for r in records]

    har = {
        "log": {
            "version": "1.2",
            "creator": {
                "name": creator_name,
                "version": "1.0.0",
            },
            "entries": entries,
        }
    }

    # Add pages if we have activity info
    pages = _extract_pages(records)
    if pages:
        har["log"]["pages"] = pages

    return har


def export_har_json(records: list[TraceRecord], indent: int = 2) -> str:
    """Export TraceRecords as a HAR JSON string."""
    return json.dumps(export_har(records), indent=indent, default=str)


def import_har(har_data: dict) -> list[dict]:
    """Import HAR entries into a common format for replay.

    Returns a list of dicts with standardized request/response data.
    """
    entries = har_data.get("log", {}).get("entries", [])
    result = []

    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})

        result.append({
            "method": request.get("method", "GET"),
            "url": request.get("url", ""),
            "request_headers": {
                h["name"]: h["value"]
                for h in request.get("headers", [])
            },
            "request_body": _get_post_data(request),
            "response_status": response.get("status", 0),
            "response_headers": {
                h["name"]: h["value"]
                for h in response.get("headers", [])
            },
            "response_body": response.get("content", {}).get("text", ""),
            "response_time_ms": entry.get("time", 0),
        })

    return result


def _record_to_har_entry(record: TraceRecord) -> dict:
    """Convert a single TraceRecord to a HAR entry."""
    # Parse URL for query string
    parsed = urlparse(record.url)
    query_params = parse_qs(parsed.query)

    # Build request
    request: dict = {
        "method": record.method,
        "url": record.url,
        "httpVersion": "HTTP/1.1",
        "headers": [
            {"name": k, "value": v}
            for k, v in record.request_headers.items()
        ],
        "queryString": [
            {"name": k, "value": v[0] if v else ""}
            for k, v in query_params.items()
        ],
        "cookies": [],
        "headersSize": -1,
        "bodySize": len(record.request_body_raw) if record.request_body_raw else 0,
    }

    # Add POST data if present
    if record.request_body_raw:
        content_type = record.request_headers.get("Content-Type", "application/octet-stream")
        request["postData"] = {
            "mimeType": content_type,
            "text": record.request_body_raw.decode("utf-8", errors="replace"),
        }

    # Build response
    response: dict = {
        "status": record.response_status or 0,
        "statusText": _status_text(record.response_status),
        "httpVersion": "HTTP/1.1",
        "headers": [
            {"name": k, "value": v}
            for k, v in (record.response_headers or {}).items()
        ],
        "cookies": [],
        "content": {
            "size": len(record.response_body_raw) if record.response_body_raw else 0,
            "mimeType": (record.response_headers or {}).get(
                "Content-Type", "application/octet-stream"
            ),
        },
        "redirectURL": "",
        "headersSize": -1,
        "bodySize": len(record.response_body_raw) if record.response_body_raw else 0,
    }

    if record.response_body_raw:
        response["content"]["text"] = record.response_body_raw.decode("utf-8", errors="replace")

    # Build entry
    start_time = datetime.fromtimestamp(
        record.timestamp_ms / 1000, tz=timezone.utc
    ).isoformat()

    entry: dict = {
        "startedDateTime": start_time,
        "time": record.response_time_ms or 0,
        "request": request,
        "response": response,
        "cache": {},
        "timings": {
            "send": 0,
            "wait": record.response_time_ms or 0,
            "receive": 0,
        },
    }

    # Add custom fields for context
    if record.ui_activity:
        entry["_ui_activity"] = record.ui_activity
    if record.invoking_class:
        entry["_invoking_class"] = record.invoking_class

    return entry


def _extract_pages(records: list[TraceRecord]) -> list[dict]:
    """Extract page references from unique activities."""
    activities = set()
    pages = []

    for r in records:
        if r.ui_activity and r.ui_activity not in activities:
            activities.add(r.ui_activity)
            pages.append({
                "startedDateTime": datetime.fromtimestamp(
                    r.timestamp_ms / 1000, tz=timezone.utc
                ).isoformat(),
                "id": r.ui_activity,
                "title": r.ui_activity,
            })

    return pages


def _get_post_data(request: dict) -> Optional[str]:
    """Extract POST data from a HAR request."""
    post_data = request.get("postData")
    if post_data:
        return post_data.get("text")
    return None


def _status_text(status: Optional[int]) -> str:
    """Map HTTP status code to text."""
    status_map = {
        200: "OK", 201: "Created", 204: "No Content",
        301: "Moved Permanently", 302: "Found", 304: "Not Modified",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
        422: "Unprocessable Entity", 429: "Too Many Requests",
        500: "Internal Server Error", 502: "Bad Gateway",
        503: "Service Unavailable",
    }
    return status_map.get(status or 0, "Unknown")
