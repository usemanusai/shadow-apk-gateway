"""Tests for the OkHttp smali parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from packages.core_schema.models.ingest_manifest import IngestManifest
from apps.extractor.src.parsers.okhttp import parse_okhttp


def _make_manifest(fixture_name: str) -> IngestManifest:
    fixture_dir = Path(__file__).parent.parent / "fixtures" / fixture_name
    return IngestManifest(
        apk_sha256="test",
        package_name="com.example.testapp",
        decompiled_root=str(fixture_dir),
        smali_dirs=[str(fixture_dir / "smali")],
    )


class TestOkHttpParser:
    """Test suite for the OkHttp parser."""

    def test_finds_url_strings(self):
        """Parser should find URL strings used with OkHttp builders."""
        manifest = _make_manifest("okhttp_sample")
        findings = parse_okhttp(manifest)

        urls = [f.url_path for f in findings]
        assert any("api.example.com/v2/products" in u for u in urls), \
            f"Expected products URL in: {urls}"

    def test_detects_http_methods(self):
        """Parser should detect GET/POST/DELETE from builder chains."""
        manifest = _make_manifest("okhttp_sample")
        findings = parse_okhttp(manifest)

        methods = [f.method for f in findings if f.method]
        assert "GET" in methods or "POST" in methods or "DELETE" in methods, \
            f"Expected HTTP methods in: {methods}"

    def test_extracts_headers(self):
        """Parser should extract addHeader calls."""
        manifest = _make_manifest("okhttp_sample")
        findings = parse_okhttp(manifest)

        all_params = []
        for f in findings:
            all_params.extend(f.parameters)
        header_names = {p.name for p in all_params if p.location == "header"}

        # Should find at least Authorization or Content-Type
        assert len(header_names) > 0, "Expected header parameters"

    def test_parser_name_set(self):
        """All findings should have parser_name='okhttp'."""
        manifest = _make_manifest("okhttp_sample")
        findings = parse_okhttp(manifest)

        for f in findings:
            assert f.parser_name == "okhttp"

    def test_empty_input(self):
        """Parser should return empty list for non-existent directory."""
        manifest = IngestManifest(
            apk_sha256="test",
            package_name="com.example.empty",
            decompiled_root="/nonexistent",
            smali_dirs=["/nonexistent/smali"],
        )
        findings = parse_okhttp(manifest)
        assert findings == []

    def test_no_false_positives_on_retrofit_smali(self):
        """Parser should not find OkHttp patterns in Retrofit-only smali."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_okhttp(manifest)
        assert len(findings) == 0
