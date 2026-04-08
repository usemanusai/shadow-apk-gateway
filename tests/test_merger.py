"""Tests for the URL normalizer and merger."""

import pytest
from packages.trace_model.src.merger import (
    normalize_url,
    generate_action_id,
    merge,
)
from packages.core_schema.models.raw_finding import RawStaticFinding, ParameterFinding


class TestURLNormalizer:
    """Test URL normalization for clustering."""

    def test_uuid_replacement(self):
        url = "/api/users/550e8400-e29b-41d4-a716-446655440000/profile"
        result = normalize_url(url)
        assert result == "/api/users/{uuid}/profile"

    def test_integer_id_replacement(self):
        url = "/api/orders/12345"
        result = normalize_url(url)
        assert result == "/api/orders/{id}"

    def test_base64_token_replacement(self):
        url = "/api/validate/dGhpcyBpcyBhIGxvbmcgYmFzZTY0IHRva2VuIHZhbHVl"
        result = normalize_url(url)
        assert result == "/api/validate/{token}"

    def test_hex_hash_replacement(self):
        url = "/api/files/abcdef1234567890abcdef"
        result = normalize_url(url)
        assert result == "/api/files/{hash}"

    def test_preserves_normal_segments(self):
        url = "/api/v2/users/search"
        result = normalize_url(url)
        assert result == "/api/v2/users/search"

    def test_strips_trailing_slash(self):
        url = "/api/users/"
        result = normalize_url(url)
        assert result == "/api/users"

    def test_handles_full_url(self):
        url = "https://api.example.com/v1/orders/42"
        result = normalize_url(url)
        assert "{id}" in result


class TestActionIdGeneration:
    """Test deterministic action ID generation."""

    def test_stable_ids(self):
        id1 = generate_action_id("com.example.app", "GET", "/api/users")
        id2 = generate_action_id("com.example.app", "GET", "/api/users")
        assert id1 == id2

    def test_different_methods_different_ids(self):
        id1 = generate_action_id("com.example.app", "GET", "/api/users")
        id2 = generate_action_id("com.example.app", "POST", "/api/users")
        assert id1 != id2

    def test_different_packages_different_ids(self):
        id1 = generate_action_id("com.example.app", "GET", "/api/users")
        id2 = generate_action_id("com.other.app", "GET", "/api/users")
        assert id1 != id2


class TestMerger:
    """Test the full merge pipeline."""

    def test_merge_static_only(self):
        findings = [
            RawStaticFinding(
                finding_id="123",
                parser_name="retrofit",
                source_file="com/example/ApiService.smali",
                url_path="/api/v1/users",
                method="GET",
                base_url="https://api.example.com",
                parameters=[],
                is_dynamic_url=False,
            ),
        ]

        catalog = merge(
            static_findings=findings,
            trace_records=[],
            package_name="com.example.app",
        )

        assert catalog.total_actions == 1
        assert catalog.actions[0].source == "static"
        assert catalog.actions[0].method == "GET"

    def test_merge_deduplicates(self):
        """Same URL+method from two parsers should produce one action."""
        findings = [
            RawStaticFinding(
                finding_id="1",
                parser_name="retrofit",
                source_file="file1.smali",
                url_path="/api/users",
                method="GET",
                base_url="https://api.example.com",
                parameters=[],
                is_dynamic_url=False,
            ),
            RawStaticFinding(
                finding_id="2",
                parser_name="okhttp",
                source_file="file2.smali",
                url_path="/api/users",
                method="GET",
                base_url="https://api.example.com",
                parameters=[],
                is_dynamic_url=False,
            ),
        ]

        catalog = merge(
            static_findings=findings,
            trace_records=[],
            package_name="com.example.app",
        )

        assert catalog.total_actions == 1
        assert len(catalog.actions[0].evidence) == 2
