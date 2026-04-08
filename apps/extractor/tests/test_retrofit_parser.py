"""Tests for the Retrofit smali parser."""

import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from packages.core_schema.models.ingest_manifest import IngestManifest
from apps.extractor.src.parsers.retrofit import parse_retrofit


def _make_manifest(fixture_name: str) -> IngestManifest:
    """Create an IngestManifest pointing to a fixture directory."""
    fixture_dir = Path(__file__).parent.parent / "fixtures" / fixture_name
    return IngestManifest(
        apk_sha256="test",
        package_name="com.example.testapp",
        decompiled_root=str(fixture_dir),
        smali_dirs=[str(fixture_dir / "smali")],
    )


class TestRetrofitParser:
    """Test suite for the Retrofit parser."""

    def test_finds_all_endpoints(self):
        """Parser should find all annotated endpoints in the fixture."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_retrofit(manifest)

        assert len(findings) >= 6, f"Expected at least 6 findings, got {len(findings)}"

        # Extract methods and paths
        endpoints = [(f.method, f.url_path) for f in findings]

        assert ("GET", "/api/v1/users") in endpoints
        assert ("GET", "/api/v1/users/{user_id}") in endpoints
        assert ("POST", "/api/v1/users") in endpoints
        assert ("PUT", "/api/v1/users/{user_id}") in endpoints
        assert ("DELETE", "/api/v1/users/{user_id}") in endpoints
        assert ("GET", "/api/v1/users/search") in endpoints

    def test_extracts_path_params(self):
        """Parser should extract @Path annotations."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_retrofit(manifest)

        # Find the GET /users/{user_id} endpoint
        get_by_id = [
            f for f in findings
            if f.method == "GET" and f.url_path == "/api/v1/users/{user_id}"
        ]
        assert len(get_by_id) == 1
        path_params = [p for p in get_by_id[0].parameters if p.location == "path"]
        assert len(path_params) >= 1
        assert path_params[0].name == "user_id"

    def test_extracts_query_params(self):
        """Parser should extract @Query annotations."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_retrofit(manifest)

        search = [f for f in findings if f.url_path == "/api/v1/users/search"]
        assert len(search) == 1
        query_params = [p for p in search[0].parameters if p.location == "query"]
        query_names = {p.name for p in query_params}
        assert "q" in query_names
        assert "page" in query_names

    def test_extracts_header_params(self):
        """Parser should extract @Header annotations."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_retrofit(manifest)

        search = [f for f in findings if f.url_path == "/api/v1/users/search"]
        assert len(search) == 1
        header_params = [p for p in search[0].parameters if p.location == "header"]
        header_names = {p.name for p in header_params}
        assert "Authorization" in header_names

    def test_correct_class_name(self):
        """Parser should correctly extract the enclosing class name."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_retrofit(manifest)

        for f in findings:
            assert f.class_name == "com.example.api.UserService"

    def test_parser_name_set(self):
        """All findings should have parser_name='retrofit'."""
        manifest = _make_manifest("retrofit_sample")
        findings = parse_retrofit(manifest)

        for f in findings:
            assert f.parser_name == "retrofit"

    def test_empty_input_returns_empty(self):
        """Parser should return empty list for non-existent directory."""
        manifest = IngestManifest(
            apk_sha256="test",
            package_name="com.example.empty",
            decompiled_root="/nonexistent",
            smali_dirs=["/nonexistent/smali"],
        )
        findings = parse_retrofit(manifest)
        assert findings == []

    def test_no_false_positives_on_clean_smali(self):
        """Parser should not produce findings on smali without Retrofit annotations."""
        # The okhttp fixture should have no Retrofit findings
        manifest = _make_manifest("okhttp_sample")
        findings = parse_retrofit(manifest)
        assert len(findings) == 0
