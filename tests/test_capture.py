"""Tests for the Capture module and TraceStore."""

import json
import pytest
from apps.analyzer.src.capture import CaptureSession
from apps.analyzer.src.trace_store import TraceStore


class TestCaptureSession:
    """Test Frida message → TraceRecord conversion."""

    def test_basic_capture(self):
        session = CaptureSession(app_id="test_app")

        message = {
            "type": "send",
            "payload": {
                "method": "GET",
                "url": "https://api.example.com/users",
                "requestHeaders": {"Authorization": "Bearer xyz"},
                "responseStatus": 200,
                "responseBodyText": '{"users": []}',
                "responseTimeMs": 150,
            },
        }

        session.on_frida_message(message)
        assert len(session.records) == 1

        record = session.records[0]
        assert record.method == "GET"
        assert record.url == "https://api.example.com/users"
        assert record.response_status == 200
        assert record.request_headers["Authorization"] == "Bearer xyz"

    def test_ignore_error_messages(self):
        session = CaptureSession(app_id="test_app")

        message = {"type": "error", "description": "something went wrong"}
        session.on_frida_message(message)
        assert len(session.records) == 0

    def test_batch_process(self):
        session = CaptureSession(app_id="test_app")
        events = [
            {"method": "GET", "url": f"https://api.example.com/item/{i}"}
            for i in range(5)
        ]
        results = session.process_events(events)
        assert len(results) == 5

    def test_clear(self):
        session = CaptureSession(app_id="test_app")
        session.process_events([{"method": "GET", "url": "https://example.com"}])
        assert len(session.records) == 1
        session.clear()
        assert len(session.records) == 0


class TestTraceStore:
    """Test SQLite-backed TraceStore."""

    def test_store_and_retrieve(self):
        session = CaptureSession(app_id="test_app")
        session.process_events([{
            "method": "POST",
            "url": "https://api.example.com/login",
            "requestBodyText": '{"user": "test"}',
            "responseStatus": 200,
            "responseBodyText": '{"token": "abc"}',
        }])

        store = TraceStore(":memory:")
        store.store_traces(session.records)

        retrieved = store.get_traces_by_session(session.session_id)
        assert len(retrieved) == 1
        assert retrieved[0].method == "POST"
        assert retrieved[0].url == "https://api.example.com/login"
        assert retrieved[0].response_status == 200

    def test_compressed_bodies(self):
        """Bodies should be stored compressed but retrieved decompressed."""
        session = CaptureSession(app_id="test_app")
        large_body = json.dumps({"data": "x" * 10000})
        session.process_events([{
            "method": "GET",
            "url": "https://api.example.com/data",
            "responseStatus": 200,
            "responseBodyText": large_body,
        }])

        store = TraceStore(":memory:")
        store.store_traces(session.records)

        retrieved = store.get_traces_by_session(session.session_id)
        assert retrieved[0].response_body_raw is not None
        assert large_body.encode() in retrieved[0].response_body_raw or \
            retrieved[0].response_body_raw.decode("utf-8") == large_body

    def test_query_by_url(self):
        session = CaptureSession(app_id="test")
        session.process_events([
            {"method": "GET", "url": "https://api.example.com/users"},
            {"method": "POST", "url": "https://api.example.com/login"},
            {"method": "GET", "url": "https://api.example.com/users/123"},
        ])

        store = TraceStore(":memory:")
        store.store_traces(session.records)

        results = store.get_traces_by_url("users")
        assert len(results) == 2
