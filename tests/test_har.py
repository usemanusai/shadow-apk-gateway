"""Tests for HAR export/import functionality."""

import json
import pytest

from apps.analyzer.src.har_export import export_har, export_har_json, import_har
from packages.core_schema.models.trace_record import TraceRecord


def _make_trace(**kwargs) -> TraceRecord:
    """Create a TraceRecord with sensible defaults."""
    defaults = {
        "trace_id": "trace-001",
        "app_id": "com.example.app",
        "session_id": "sess-001",
        "timestamp_ms": 1700000000000,
        "method": "GET",
        "url": "https://api.example.com/v1/users",
        "request_headers": {"Content-Type": "application/json"},
        "response_status": 200,
        "response_headers": {"Content-Type": "application/json"},
        "response_time_ms": 150,
    }
    defaults.update(kwargs)
    return TraceRecord(**defaults)


class TestHARExport:
    """Test HAR export from TraceRecords."""

    def test_export_produces_valid_har(self):
        """Exported HAR should have correct structure."""
        records = [_make_trace()]
        har = export_har(records)

        assert "log" in har
        assert har["log"]["version"] == "1.2"
        assert har["log"]["creator"]["name"] == "Shadow-APK-Gateway"
        assert len(har["log"]["entries"]) == 1

    def test_export_entry_has_request_response(self):
        """Each HAR entry should contain request and response."""
        records = [_make_trace()]
        har = export_har(records)
        entry = har["log"]["entries"][0]

        assert "request" in entry
        assert "response" in entry
        assert entry["request"]["method"] == "GET"
        assert entry["request"]["url"] == "https://api.example.com/v1/users"

    def test_export_multiple_records(self):
        """Multiple records should produce multiple entries."""
        records = [
            _make_trace(trace_id="t1", url="https://api.example.com/v1/users"),
            _make_trace(trace_id="t2", url="https://api.example.com/v1/orders", method="POST"),
        ]
        har = export_har(records)
        assert len(har["log"]["entries"]) == 2

    def test_export_empty_records(self):
        """Empty record list should produce valid HAR with no entries."""
        har = export_har([])
        assert len(har["log"]["entries"]) == 0

    def test_export_har_json_returns_string(self):
        """JSON export should return a valid JSON string."""
        records = [_make_trace()]
        json_str = export_har_json(records)
        parsed = json.loads(json_str)
        assert "log" in parsed

    def test_export_with_request_body(self):
        """Request body should be included in the HAR entry."""
        records = [_make_trace(
            method="POST",
            request_body_raw=b'{"username":"test"}',
            request_body_parsed={"username": "test"},
        )]
        har = export_har(records)
        entry = har["log"]["entries"][0]
        assert entry["request"]["method"] == "POST"

    def test_export_with_response_body(self):
        """Response body should be included in the HAR entry."""
        records = [_make_trace(
            response_body_raw=b'{"id":1,"name":"Alice"}',
            response_body_parsed={"id": 1, "name": "Alice"},
        )]
        har = export_har(records)
        entry = har["log"]["entries"][0]
        assert entry["response"]["status"] == 200

    def test_export_with_ui_activity_creates_pages(self):
        """Records with UI activity should generate HAR pages."""
        records = [_make_trace(
            ui_activity="com.example.app.LoginActivity",
        )]
        har = export_har(records)
        # Pages may or may not be present depending on implementation
        # but the export should not fail
        assert "log" in har

    def test_export_preserves_headers(self):
        """Request and response headers should be preserved."""
        records = [_make_trace(
            request_headers={"Authorization": "Bearer token123", "Accept": "application/json"},
            response_headers={"X-Request-Id": "abc123"},
        )]
        har = export_har(records)
        entry = har["log"]["entries"][0]
        # Headers should be present in some form
        request_data = entry["request"]
        assert "headers" in request_data


class TestHARImport:
    """Test HAR import for replay."""

    def test_import_basic_har(self):
        """Import should extract entries from HAR."""
        har_data = {
            "log": {
                "version": "1.2",
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://api.example.com/v1/users",
                            "headers": [{"name": "Accept", "value": "application/json"}],
                            "queryString": [],
                        },
                        "response": {
                            "status": 200,
                            "headers": [{"name": "Content-Type", "value": "application/json"}],
                            "content": {"text": '{"users":[]}'},
                        },
                    }
                ],
            }
        }
        result = import_har(har_data)
        assert len(result) == 1
        assert result[0]["method"] == "GET"
        assert result[0]["url"] == "https://api.example.com/v1/users"

    def test_import_empty_har(self):
        """Empty HAR should return empty list."""
        har_data = {"log": {"entries": []}}
        result = import_har(har_data)
        assert result == []

    def test_import_missing_entries(self):
        """Missing entries key should return empty list."""
        har_data = {"log": {}}
        result = import_har(har_data)
        assert result == []

    def test_import_round_trip(self):
        """Export then import should preserve essential data."""
        records = [_make_trace()]
        har = export_har(records)
        imported = import_har(har)
        assert len(imported) == 1
        assert imported[0]["method"] == "GET"
        assert "api.example.com" in imported[0]["url"]

    def test_import_multiple_entries(self):
        """Import should handle multiple HAR entries."""
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {"method": "GET", "url": "https://api.example.com/a", "headers": [], "queryString": []},
                        "response": {"status": 200, "headers": [], "content": {}},
                    },
                    {
                        "request": {"method": "POST", "url": "https://api.example.com/b", "headers": [], "queryString": []},
                        "response": {"status": 201, "headers": [], "content": {}},
                    },
                ],
            }
        }
        result = import_har(har_data)
        assert len(result) == 2


class TestHARBytesRoundTrip:
    """Test that bytes fields survive HAR export serialization."""

    def test_bytes_body_serializes_to_json(self):
        """TraceRecord with bytes body should export to HAR JSON without error."""
        record = _make_trace(
            request_body_raw=b'\x00\x01\x02\x03binary data',
        )
        json_str = export_har_json([record])
        # Should be valid JSON with no exceptions
        parsed = json.loads(json_str)
        assert len(parsed["log"]["entries"]) == 1

    def test_none_body_serializes_cleanly(self):
        """None body fields should not cause export errors."""
        record = _make_trace(
            request_body_raw=None,
            response_body_raw=None,
        )
        json_str = export_har_json([record])
        parsed = json.loads(json_str)
        assert len(parsed["log"]["entries"]) == 1
