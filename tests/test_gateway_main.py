"""Tests for the main Gateway API router."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.gateway.src.main import _catalogs, app, load_catalog
from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject, AuthType


@pytest.fixture(autouse=True)
def setup_mock_catalog():
    """Inject a mock catalog into the global gateway state before tests."""
    catalog = ActionCatalog(
        app_id="test_api_app",
        package_name="com.test.api.app",
        version_name="2.0",
        version_code=2,
    )
    
    action1 = ActionObject(
        action_id="act-uuid-1",
        source="merged",
        app_id="test_api_app",
        package_name="com.test.api.app",
        version_name="2.0",
        version_code=2,
        method="GET",
        url_template="/api/public",
        base_url="https://api.example.com",
        params=[],
        auth_requirements=[AuthType.NONE],
        confidence_score=0.9,
    )
    
    action2 = ActionObject(
        action_id="act-uuid-2",
        source="dynamic",
        app_id="test_api_app",
        package_name="com.test.api.app",
        version_name="2.0",
        version_code=2,
        method="POST",
        url_template="/api/private",
        base_url="https://api.example.com",
        params=[],
        auth_requirements=[AuthType.BEARER],
        confidence_score=0.6,
        approved=True,
    )
    
    catalog.actions = [action1, action2]
    
    load_catalog(catalog)
    yield
    # Cleanup state
    _catalogs.clear()


def test_list_apps(gateway_client: TestClient):
    """Test listing of all loaded apps."""
    res = gateway_client.get("/apps")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["app_id"] == "test_api_app"


def test_list_actions(gateway_client: TestClient):
    """Test retrieving actions for an app."""
    res = gateway_client.get("/apps/test_api_app/actions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2


def test_list_actions_filters(gateway_client: TestClient):
    """Test retrieving actions with query filters."""
    # Approved filter
    res = gateway_client.get("/apps/test_api_app/actions?approved_only=true")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["action_id"] == "act-uuid-2"
    
    # Confidence filter
    res = gateway_client.get("/apps/test_api_app/actions?confidence_min=0.8")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["action_id"] == "act-uuid-1"


# === GATEWAY_CATALOGS_DIR auto-load tests ===


class TestAutoLoadCatalogs:
    """Tests for the GATEWAY_CATALOGS_DIR startup auto-load feature."""

    def _make_catalog_json(self, directory: Path) -> None:
        """Write a minimal valid catalog.json to the given directory."""
        catalog = {
            "app_id": "autoload-test",
            "package_name": "com.autoload.test",
            "version_name": "1.0.0",
            "version_code": 1,
            "actions": [
                {
                    "action_id": "auto-action-1",
                    "source": "static",
                    "app_id": "autoload-test",
                    "package_name": "com.autoload.test",
                    "version_name": "1.0.0",
                    "version_code": 1,
                    "method": "GET",
                    "url_template": "/api/test",
                    "base_url": "https://api.example.com",
                    "params": [],
                    "auth_requirements": ["none"],
                    "confidence_score": 0.8,
                    "approved": True,
                }
            ],
        }
        import json
        (directory / "catalog.json").write_text(json.dumps(catalog))

    def test_autoload_catalogs_from_dir(self, tmp_path, monkeypatch):
        """When GATEWAY_CATALOGS_DIR points to a dir with catalog.json, it is loaded."""
        self._make_catalog_json(tmp_path)
        monkeypatch.setenv("GATEWAY_CATALOGS_DIR", str(tmp_path))

        _catalogs.clear()

        # Trigger the startup handler manually
        import asyncio
        from apps.gateway.src.main import _auto_load_catalogs
        asyncio.get_event_loop().run_until_complete(_auto_load_catalogs())

        client = TestClient(app)
        res = client.get("/apps")
        assert res.status_code == 200
        data = res.json()
        app_ids = [a["app_id"] for a in data]
        assert "autoload-test" in app_ids

        # Cleanup
        _catalogs.clear()

    def test_autoload_missing_dir(self, tmp_path, monkeypatch):
        """When GATEWAY_CATALOGS_DIR points to a nonexistent dir, gateway still starts."""
        monkeypatch.setenv("GATEWAY_CATALOGS_DIR", str(tmp_path / "does_not_exist"))

        _catalogs.clear()

        import asyncio
        from apps.gateway.src.main import _auto_load_catalogs
        asyncio.get_event_loop().run_until_complete(_auto_load_catalogs())

        client = TestClient(app)
        res = client.get("/apps")
        assert res.status_code == 200
        assert res.json() == []

    def test_autoload_empty_dir(self, tmp_path, monkeypatch):
        """When GATEWAY_CATALOGS_DIR points to an empty dir, gateway starts with no catalogs."""
        monkeypatch.setenv("GATEWAY_CATALOGS_DIR", str(tmp_path))

        _catalogs.clear()

        import asyncio
        from apps.gateway.src.main import _auto_load_catalogs
        asyncio.get_event_loop().run_until_complete(_auto_load_catalogs())

        client = TestClient(app)
        res = client.get("/apps")
        assert res.status_code == 200
        assert res.json() == []

