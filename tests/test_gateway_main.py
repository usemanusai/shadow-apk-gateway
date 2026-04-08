"""Tests for the main Gateway API router."""

import pytest
from fastapi.testclient import TestClient

from apps.gateway.src.main import _catalogs, load_catalog
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
