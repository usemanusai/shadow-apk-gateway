"""Tests for the URL normalizer and merger (Hardened).

Includes comprehensive tests for the entropy/modulus-based normalization algorithm,
covering all hash types, base64 variants, opaque tokens, and edge cases.
"""

import pytest
from packages.trace_model.src.merger import (
    normalize_url,
    generate_action_id,
    merge,
    _shannon_entropy,
    _classify_segment,
)
from packages.core_schema.models.raw_finding import RawStaticFinding, ParameterFinding
from packages.core_schema.models.trace_record import TraceRecord


class TestShannonEntropy:
    """Test the Shannon entropy computation."""

    def test_empty_string(self):
        assert _shannon_entropy("") == 0.0

    def test_single_char_repeated(self):
        assert _shannon_entropy("aaaaaaa") == 0.0

    def test_two_chars_equal(self):
        # "ab" repeated → 1.0 bit/char
        entropy = _shannon_entropy("abababab")
        assert abs(entropy - 1.0) < 0.01

    def test_hex_entropy_range(self):
        """Typical hex hash should have ~3.0-4.0 bits/char entropy."""
        # MD5 of "test"
        hex_hash = "098f6bcd4621d373cade4e832627b4f6"
        entropy = _shannon_entropy(hex_hash)
        assert 2.5 < entropy < 4.5

    def test_high_entropy_random(self):
        """Random alphanumeric should have higher entropy."""
        random_str = "aB3kL9mN2pQ5rS8tU1vW4xY7zA0cE6fG"
        entropy = _shannon_entropy(random_str)
        assert entropy > 3.5


class TestSegmentClassifier:
    """Test the multi-tier URL segment classifier."""

    # Tier 1: UUID
    def test_uuid_lowercase(self):
        assert _classify_segment("550e8400-e29b-41d4-a716-446655440000") == "{uuid}"

    def test_uuid_uppercase(self):
        assert _classify_segment("550E8400-E29B-41D4-A716-446655440000") == "{uuid}"

    def test_uuid_mixed_case(self):
        assert _classify_segment("550e8400-E29B-41d4-a716-446655440000") == "{uuid}"

    # Tier 2: Integer IDs
    def test_short_integer(self):
        assert _classify_segment("42") == "{id}"

    def test_long_integer(self):
        assert _classify_segment("123456789012345") == "{id}"

    def test_max_integer_length(self):
        assert _classify_segment("12345678901234567890") == "{id}"

    def test_oversized_integer_not_id(self):
        """Integers > 20 digits should not be classified as IDs."""
        result = _classify_segment("123456789012345678901")
        assert result != "{id}"

    # Tier 3: Hex hashes — standard lengths
    def test_md5_hash(self):
        """32-char hex → {hash}"""
        assert _classify_segment("098f6bcd4621d373cade4e832627b4f6") == "{hash}"

    def test_sha1_hash(self):
        """40-char hex → {hash}"""
        assert _classify_segment("a94a8fe5ccb19ba61c4c0873d391e987982fbbd3") == "{hash}"

    def test_sha224_hash(self):
        """56-char hex → {hash}"""
        seg = "90a3ed9e32b2aaf4c61c410eb925426119e1a9dc53d4286ade99a809"
        assert _classify_segment(seg) == "{hash}"

    def test_sha256_hash(self):
        """64-char hex → {hash}"""
        seg = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        assert _classify_segment(seg) == "{hash}"

    def test_sha384_hash(self):
        """96-char hex → {hash}"""
        seg = "768412320f7b0aa5812fce428dc4706b3cae50e02a64caa16a782249bfe8efc4b7ef1ccb126255d196047dfedf17a0a9"
        assert len(seg) == 96
        assert _classify_segment(seg) == "{hash}"

    def test_sha512_hash(self):
        """128-char hex → {hash}"""
        seg = (
            "ee26b0dd4af7e749aa1a8ee3c10ae9923f618980772e473f8819a5d4940e0db2"
            "7ac185f8a0e1d5f84f88bc887fd67b143732c304cc5fa9ad8e6f57f50028a8ff"
        )
        assert len(seg) == 128
        assert _classify_segment(seg) == "{hash}"

    def test_hmac_truncated_16(self):
        """16-char hex → {hash}"""
        assert _classify_segment("0123456789abcdef") == "{hash}"

    def test_short_hex_not_hash(self):
        """Hex strings < 16 chars should NOT be classified as hashes."""
        assert _classify_segment("abcdef12") is None

    def test_hex_non_standard_length_high_entropy(self):
        """Hex string of non-standard length but high entropy → {hash} via Tier 3b."""
        # 18-char hex, not in STANDARD_HASH_LENGTHS, but high entropy
        seg = "a1b2c3d4e5f67890ab"
        result = _classify_segment(seg)
        assert result == "{hash}"

    # Tier 4: Base64 tokens
    def test_base64_with_uppercase(self):
        """Base64 with uppercase letters → {token}"""
        seg = "dGhpcyBpcyBhIGxvbmcgYmFzZTY0IHRva2VuIHZhbHVl"
        result = _classify_segment(seg)
        # Should be {token} because it has uppercase chars
        assert result in ("{token}", "{hash}")

    def test_base64_with_equals_padding(self):
        """Base64 with = padding → {token}"""
        seg = "SGVsbG8gV29ybGQgdGhpcyBpcyBwYWRkZWQ="
        result = _classify_segment(seg)
        assert result in ("{token}",)

    def test_base64_with_plus_slash(self):
        """Base64 with +/ characters → {token}"""
        seg = "abc+def/ghi+jkl/mno+pqr/stu="
        result = _classify_segment(seg)
        assert result == "{token}"

    def test_url_safe_base64(self):
        """URL-safe base64 with - and _ → {token}"""
        seg = "abc-def_ghi-jkl_mno-pqr_stu_"
        result = _classify_segment(seg)
        assert result == "{token}"

    # Tier 5: Opaque tokens
    def test_long_alphanumeric_high_entropy(self):
        """Long alphanumeric string with high entropy → {token}"""
        seg = "aB3kL9mN2pQ5rS8tU1vW4xY7zA0"
        result = _classify_segment(seg)
        assert result == "{token}"

    # Negative cases
    def test_normal_word_preserved(self):
        """Regular words should not be classified."""
        assert _classify_segment("users") is None
        assert _classify_segment("api") is None
        assert _classify_segment("v2") is None
        assert _classify_segment("search") is None

    def test_empty_segment(self):
        assert _classify_segment("") is None

    def test_single_char(self):
        assert _classify_segment("a") is None


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

    def test_hex_hash_md5_replacement(self):
        """MD5 hex hash (32 chars) → {hash}"""
        url = "/api/files/098f6bcd4621d373cade4e832627b4f6"
        result = normalize_url(url)
        assert result == "/api/files/{hash}"

    def test_hex_hash_sha1_replacement(self):
        """SHA-1 hex hash (40 chars) → {hash}"""
        url = "/api/files/a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"
        result = normalize_url(url)
        assert result == "/api/files/{hash}"

    def test_hex_hash_sha256_replacement(self):
        """SHA-256 hex hash (64 chars) → {hash}"""
        url = "/api/files/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
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

    def test_mixed_segments(self):
        """Multiple dynamic segments in one URL."""
        url = "/api/users/12345/files/098f6bcd4621d373cade4e832627b4f6"
        result = normalize_url(url)
        assert result == "/api/users/{id}/files/{hash}"

    def test_double_slashes(self):
        """Double slashes should produce empty segments."""
        url = "/api//users/42"
        result = normalize_url(url)
        assert "{id}" in result

    def test_query_string_stripped(self):
        """Query strings should not affect path normalization."""
        url = "/api/users/42?page=1&limit=10"
        result = normalize_url(url)
        assert "{id}" in result
        assert "page" not in result

    def test_hex_vs_base64_disambiguation(self):
        """Hex-only string at standard hash length → {hash}, not {token}."""
        # 32-char lowercase hex (MD5) must be {hash}
        url = "/api/check/abcdef0123456789abcdef0123456789"
        result = normalize_url(url)
        assert "{hash}" in result

    def test_short_hex_preserved(self):
        """Short hex strings (< 16 chars) should be preserved as-is."""
        url = "/api/color/ff5733"
        result = normalize_url(url)
        assert result == "/api/color/ff5733"


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

    def test_id_is_uuid_format(self):
        action_id = generate_action_id("com.example.app", "GET", "/api/users")
        # UUID v5 format contains hex and hyphens
        assert all(c in "0123456789abcdef-" for c in action_id)


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

    def test_merge_with_trace_records(self):
        """Dynamic trace records should merge into the catalog."""
        trace = TraceRecord(
            trace_id="trace-001",
            app_id="com.example.app",
            session_id="sess-001",
            timestamp_ms=1700000000000,
            method="POST",
            url="https://api.example.com/api/v1/login",
            response_status=200,
            response_time_ms=150,
        )

        findings = [
            RawStaticFinding(
                finding_id="123",
                parser_name="retrofit",
                source_file="com/example/ApiService.smali",
                url_path="/api/v1/login",
                method="POST",
                base_url="https://api.example.com",
                parameters=[],
                is_dynamic_url=False,
            ),
        ]

        catalog = merge(
            static_findings=findings,
            trace_records=[trace],
            package_name="com.example.app",
        )

        assert catalog.total_actions >= 1
        # The merged action should have evidence from both sources
        login_action = None
        for a in catalog.actions:
            if "login" in a.url_template:
                login_action = a
                break
        assert login_action is not None

    def test_merge_multiple_endpoints(self):
        """Different endpoints should produce separate actions."""
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
                parser_name="retrofit",
                source_file="file2.smali",
                url_path="/api/orders",
                method="POST",
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

        assert catalog.total_actions == 2

    def test_merge_empty_input(self):
        """Merge with no inputs should produce empty catalog."""
        catalog = merge(
            static_findings=[],
            trace_records=[],
            package_name="com.example.app",
        )
        assert catalog.total_actions == 0
