"""Tests for the Retrofit smali parser."""

import pytest
from pathlib import Path

from apps.extractor.src.parsers.retrofit import parse_retrofit
from packages.core_schema.models.ingest_manifest import IngestManifest


def test_parse_retrofit_finds_endpoints(mock_manifest: IngestManifest, tmp_path: Path):
    """Test that Retrofit parser correctly identifies endpoints and path/header/body params."""
    smali_dir = tmp_path / "com" / "example" / "api"
    smali_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy the sample we created
    sample_path = Path("tests/fixtures/smali/RetrofitSample.smali")
    if sample_path.exists():
        (smali_dir / "RetrofitSample.smali").write_text(sample_path.read_text())
    
    findings = parse_retrofit(mock_manifest)
    
    assert len(findings) == 2
    
    # Sort to ensure consistent checking
    findings.sort(key=lambda f: f.url_path)
    
    # 1. POST updateSettings
    post_finding = findings[0]
    assert post_finding.method == "POST"
    assert post_finding.url_path == "/api/v1/settings/update"
    assert post_finding.class_name == "com.example.api.RetrofitService"
    assert post_finding.method_name == "updateSettings"
    assert len(post_finding.parameters) == 1
    
    headers = [p for p in post_finding.parameters if p.location == "header"]
    assert len(headers) == 1
    assert headers[0].name == "Authorization"
    
    bodies = [p for p in post_finding.parameters if p.location == "body"]
    assert len(bodies) == 0
    
    # 2. GET getUserProfile
    get_finding = findings[1]
    assert get_finding.method == "GET"
    assert get_finding.url_path == "/api/v1/users/{userId}/profile"
    assert len(get_finding.parameters) == 1
    
    paths = [p for p in get_finding.parameters if p.location == "path"]
    assert len(paths) == 1
    assert paths[0].name == "userId"
