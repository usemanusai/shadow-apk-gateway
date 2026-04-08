"""Tests for the OkHttp static smali parser."""

import pytest
from pathlib import Path

from apps.extractor.src.parsers.okhttp import parse_okhttp
from packages.core_schema.models.ingest_manifest import IngestManifest


def test_parse_okhttp_finds_builder(mock_manifest: IngestManifest, tmp_path: Path):
    """Test that OkHttp parser extracts builder usage including URL and Headers."""
    smali_dir = tmp_path / "com" / "example" / "api"
    smali_dir.mkdir(parents=True, exist_ok=True)
    
    sample_path = Path("tests/fixtures/smali/OkHttpSample.smali")
    if sample_path.exists():
        (smali_dir / "OkHttpSample.smali").write_text(sample_path.read_text())
        
    findings = parse_okhttp(mock_manifest)
    valid_findings = [f for f in findings if f.method == "GET"]
    assert len(valid_findings) > 0
    finding = valid_findings[0]
    
    assert finding.parser_name == "okhttp"
    assert finding.url_path == "https://api.example.com/v1/data"
    assert finding.method == "GET"
    assert finding.class_name == "com.example.api.OkHttpService"
    
    # Should extract added headers
    header_names = {p.name for p in finding.parameters if p.location == "header"}
    assert "Authorization" in header_names
    assert "X-Client-ID" in header_names
