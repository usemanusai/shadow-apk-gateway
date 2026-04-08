"""Tests for the Replay Engine — Replayer and Differ."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from packages.replay_engine.src.replayer import (
    Replayer,
    ReplayConfig,
    ReplayResult,
    _jaccard_keys,
    _extract_keys,
)
from packages.replay_engine.src.differ import Differ, DiffEntry, DiffReport


# ═══════════════════════════════════════════════════════════════════════════════
# Replayer Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestReplayConfig:
    """Test replay configuration."""

    def test_default_config(self):
        config = ReplayConfig()
        assert config.speed_multiplier == 1.0
        assert config.timeout == 30.0
        assert config.respect_timing is True

    def test_custom_config(self):
        config = ReplayConfig(speed_multiplier=2.0, timeout=10.0, respect_timing=False)
        assert config.speed_multiplier == 2.0
        assert config.timeout == 10.0
        assert config.respect_timing is False


class TestReplayResult:
    """Test ReplayResult data class."""

    def test_success_result(self):
        result = ReplayResult(
            entry_index=0,
            original_url="https://api.example.com/v1/users",
            original_method="GET",
            original_status=200,
            replayed_status=200,
            status_match=True,
            body_similarity=0.95,
            latency_ms=150,
        )
        assert result.is_success is True

    def test_failure_result(self):
        result = ReplayResult(
            entry_index=0,
            original_url="https://api.example.com/v1/users",
            original_method="GET",
            original_status=200,
            replayed_status=500,
            status_match=False,
            body_similarity=0.0,
            latency_ms=300,
        )
        assert result.is_success is False

    def test_error_result(self):
        result = ReplayResult(
            entry_index=0,
            original_url="https://api.example.com/v1/users",
            original_method="GET",
            original_status=200,
            replayed_status=0,
            status_match=False,
            body_similarity=0.0,
            latency_ms=0,
            error="Connection refused",
        )
        assert result.is_success is False


class TestBodySimilarity:
    """Test body similarity computation."""

    def test_identical_bodies(self):
        similarity = Replayer._compute_body_similarity(
            '{"users": []}', '{"users": []}'
        )
        assert similarity == 1.0

    def test_empty_bodies(self):
        similarity = Replayer._compute_body_similarity("", "")
        assert similarity == 1.0

    def test_one_empty_body(self):
        similarity = Replayer._compute_body_similarity('{"data": 1}', "")
        assert similarity == 0.0

    def test_similar_json_bodies(self):
        original = '{"users": [], "total": 10, "page": 1}'
        replayed = '{"users": [], "total": 20, "page": 2}'
        similarity = Replayer._compute_body_similarity(original, replayed)
        # Same keys, different values → Jaccard = 1.0
        assert similarity == 1.0

    def test_different_json_bodies(self):
        original = '{"users": [], "total": 10}'
        replayed = '{"error": "not found"}'
        similarity = Replayer._compute_body_similarity(original, replayed)
        # Different keys → low similarity
        assert similarity < 1.0

    def test_text_similarity(self):
        similarity = Replayer._compute_body_similarity("Hello World", "Hello")
        assert 0.0 < similarity < 1.0


class TestJaccardKeys:
    """Test Jaccard key similarity computation."""

    def test_identical_objects(self):
        assert _jaccard_keys({"a": 1, "b": 2}, {"a": 3, "b": 4}) == 1.0

    def test_empty_objects(self):
        assert _jaccard_keys({}, {}) == 1.0

    def test_disjoint_objects(self):
        assert _jaccard_keys({"a": 1}, {"b": 2}) == 0.0

    def test_partial_overlap(self):
        similarity = _jaccard_keys({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert 0.0 < similarity < 1.0
        # Jaccard: |{b}| / |{a, b, c}| = 1/3
        assert abs(similarity - 1 / 3) < 0.01


class TestExtractKeys:
    """Test recursive key extraction."""

    def test_flat_object(self):
        keys = _extract_keys({"name": "Alice", "age": 30})
        assert "name" in keys
        assert "age" in keys

    def test_nested_object(self):
        keys = _extract_keys({"user": {"name": "Alice", "email": "alice@example.com"}})
        assert "user" in keys
        assert "user.name" in keys
        assert "user.email" in keys

    def test_array_object(self):
        keys = _extract_keys({"items": [{"id": 1, "name": "Item 1"}]})
        assert "items" in keys

    def test_empty_object(self):
        keys = _extract_keys({})
        assert len(keys) == 0


class TestReplayerExecution:
    """Test the replayer execution with mocked HTTP."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.request")
    async def test_replay_single_entry(self, mock_request):
        mock_response = httpx.Response(
            status_code=200,
            text='{"users": []}',
            request=httpx.Request("GET", "https://api.example.com/v1/users"),
        )
        mock_request.return_value = mock_response

        config = ReplayConfig(respect_timing=False)
        replayer = Replayer(config)
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://api.example.com/v1/users",
                            "headers": [],
                        },
                        "response": {
                            "status": 200,
                            "content": {"text": '{"users": []}'},
                        },
                    }
                ]
            }
        }

        results = await replayer.replay_har(har_data)
        assert len(results) == 1
        assert results[0].status_match is True
        assert results[0].body_similarity == 1.0

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.request")
    async def test_replay_handles_timeout(self, mock_request):
        mock_request.side_effect = httpx.TimeoutException("Timeout")

        config = ReplayConfig(respect_timing=False)
        replayer = Replayer(config)
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://api.example.com/timeout",
                            "headers": [],
                        },
                        "response": {"status": 200},
                    }
                ]
            }
        }

        results = await replayer.replay_har(har_data)
        assert len(results) == 1
        assert results[0].error is not None
        assert results[0].is_success is False

    @pytest.mark.asyncio
    async def test_replay_empty_har(self):
        config = ReplayConfig(respect_timing=False)
        replayer = Replayer(config)
        results = await replayer.replay_har({"log": {"entries": []}})
        assert results == []


# ═══════════════════════════════════════════════════════════════════════════════
# Differ Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiffReport:
    """Test DiffReport data class."""

    def test_empty_report(self):
        report = DiffReport()
        assert report.has_hard_failures is False
        assert report.overall_similarity == 1.0

    def test_report_with_failures(self):
        report = DiffReport(hard_failures=2)
        assert report.has_hard_failures is True

    def test_report_to_dict(self):
        report = DiffReport(total_entries=5, successful_replays=3, hard_failures=1, warnings=1)
        d = report.to_dict()
        assert d["total_entries"] == 5
        assert d["successful_replays"] == 3


class TestDiffer:
    """Test the Differ comparison engine."""

    def test_status_mismatch_is_hard_failure(self):
        differ = Differ()
        results = [
            ReplayResult(
                entry_index=0,
                original_url="https://api.example.com/test",
                original_method="GET",
                original_status=200,
                replayed_status=500,
                status_match=False,
                body_similarity=0.0,
                latency_ms=100,
            )
        ]
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {"method": "GET", "url": "https://api.example.com/test"},
                        "response": {"status": 200, "content": {}},
                    }
                ]
            }
        }

        report = differ.compare(results, har_data)
        assert report.hard_failures >= 1
        assert any(d.diff_type == "status_mismatch" for d in report.diffs)

    def test_successful_replay_no_diffs(self):
        differ = Differ()
        results = [
            ReplayResult(
                entry_index=0,
                original_url="https://api.example.com/test",
                original_method="GET",
                original_status=200,
                replayed_status=200,
                status_match=True,
                body_similarity=0.95,
                latency_ms=100,
            )
        ]
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {"method": "GET", "url": "https://api.example.com/test"},
                        "response": {"status": 200, "content": {}},
                    }
                ]
            }
        }

        report = differ.compare(results, har_data)
        assert report.hard_failures == 0
        assert report.successful_replays == 1

    def test_body_drift_warning(self):
        differ = Differ(similarity_threshold=0.85)
        results = [
            ReplayResult(
                entry_index=0,
                original_url="https://api.example.com/test",
                original_method="GET",
                original_status=200,
                replayed_status=200,
                status_match=True,
                body_similarity=0.70,  # Below threshold but above 0.5
                latency_ms=100,
            )
        ]
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {"method": "GET", "url": "https://api.example.com/test"},
                        "response": {"status": 200, "content": {}},
                    }
                ]
            }
        }

        report = differ.compare(results, har_data)
        assert report.warnings >= 1
        assert any(d.diff_type == "body_drift" for d in report.diffs)

    def test_execution_error_is_hard_failure(self):
        differ = Differ()
        results = [
            ReplayResult(
                entry_index=0,
                original_url="https://api.example.com/test",
                original_method="GET",
                original_status=200,
                replayed_status=0,
                status_match=False,
                body_similarity=0.0,
                latency_ms=0,
                error="Connection refused",
            )
        ]
        har_data = {
            "log": {
                "entries": [
                    {
                        "request": {"method": "GET", "url": "https://api.example.com/test"},
                        "response": {"status": 200, "content": {}},
                    }
                ]
            }
        }

        report = differ.compare(results, har_data)
        assert report.hard_failures >= 1
        assert any(d.diff_type == "execution_error" for d in report.diffs)

    def test_overall_similarity_averaged(self):
        differ = Differ()
        results = [
            ReplayResult(0, "url1", "GET", 200, 200, True, 1.0, 100),
            ReplayResult(1, "url2", "GET", 200, 200, True, 0.8, 100),
        ]
        har_data = {
            "log": {
                "entries": [
                    {"request": {"method": "GET", "url": "url1"}, "response": {"status": 200, "content": {}}},
                    {"request": {"method": "GET", "url": "url2"}, "response": {"status": 200, "content": {}}},
                ]
            }
        }

        report = differ.compare(results, har_data)
        assert abs(report.overall_similarity - 0.9) < 0.01

    def test_generate_summary(self):
        differ = Differ()
        report = DiffReport(total_entries=3, successful_replays=2, hard_failures=1)
        summary = differ.generate_summary(report)
        assert "Total entries: 3" in summary
        assert "Hard failures: 1" in summary
