import pytest
from fastapi.testclient import TestClient

from apps.gateway.src.main import app
from packages.core_schema.models.ingest_manifest import IngestManifest


@pytest.fixture
def gateway_client() -> TestClient:
    """Provide a test client for the gateway app."""
    return TestClient(app)


@pytest.fixture
def mock_manifest(tmp_path) -> IngestManifest:
    """Provide a dummy IngestManifest for extractor tests."""
    return IngestManifest(
        apk_sha256="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        package_name="com.test.app",
        version_name="1.0.0",
        version_code=1,
        decompiled_root=str(tmp_path),
        smali_dirs=[str(tmp_path)],
        asset_dirs=[],
        min_sdk=21,
        target_sdk=33,
    )
