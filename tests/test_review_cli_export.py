"""Tests for the Review CLI export command."""

import json
from pathlib import Path

import yaml

from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject, AuthType, ParamSchema
from apps.gateway.src.review_cli import _export_openapi


def _make_export_catalog() -> ActionCatalog:
    """Create a test catalog with one approved and one unapproved action."""
    approved_action = ActionObject(
        action_id="export-approved-001",
        source="static",
        app_id="export-test",
        package_name="com.export.test",
        version_name="2.0.0",
        version_code=2,
        method="GET",
        url_template="/api/v1/items",
        base_url="https://api.example.com",
        params=[
            ParamSchema(name="page", location="query", required=False, type="integer"),
        ],
        auth_requirements=[AuthType.BEARER],
        confidence_score=0.85,
        approved=True,
        approved_by="tester",
    )

    unapproved_action = ActionObject(
        action_id="export-unapproved-002",
        source="static",
        app_id="export-test",
        package_name="com.export.test",
        version_name="2.0.0",
        version_code=2,
        method="POST",
        url_template="/api/v1/items",
        base_url="https://api.example.com",
        params=[
            ParamSchema(name="name", location="body", required=True, type="string"),
        ],
        auth_requirements=[AuthType.NONE],
        confidence_score=0.70,
        approved=False,
    )

    return ActionCatalog(
        app_id="export-test",
        package_name="com.export.test",
        version_name="2.0.0",
        version_code=2,
        actions=[approved_action, unapproved_action],
    )


class TestExportOpenAPI:
    """Test the _export_openapi helper and the export CLI command."""

    def test_export_creates_json_and_yaml(self, tmp_path):
        """Export should create both .openapi.json and .openapi.yaml files."""
        catalog = _make_export_catalog()
        json_path, yaml_path = _export_openapi(catalog, tmp_path)

        assert json_path.exists()
        assert yaml_path.exists()
        assert json_path.suffix == ".json"
        assert yaml_path.suffix == ".yaml"

    def test_export_json_is_valid_openapi(self, tmp_path):
        """The exported JSON should be valid OpenAPI 3.1."""
        catalog = _make_export_catalog()
        json_path, _ = _export_openapi(catalog, tmp_path)

        with open(json_path) as f:
            spec = json.load(f)

        assert spec["openapi"] == "3.1.0"
        assert "info" in spec
        assert "paths" in spec

    def test_export_default_excludes_unapproved(self, tmp_path):
        """By default, only approved actions should appear in the spec."""
        catalog = _make_export_catalog()
        json_path, _ = _export_openapi(catalog, tmp_path)

        with open(json_path) as f:
            spec = json.load(f)

        # Find execute paths (action-specific, not catalog-level endpoints)
        execute_paths = [p for p in spec["paths"] if "execute" in p]
        assert len(execute_paths) == 1
        assert "export-approved-001" in execute_paths[0]

    def test_export_include_unapproved(self, tmp_path):
        """With include_unapproved=True, both actions should appear."""
        catalog = _make_export_catalog()
        json_path, _ = _export_openapi(catalog, tmp_path, include_unapproved=True)

        with open(json_path) as f:
            spec = json.load(f)

        execute_paths = [p for p in spec["paths"] if "execute" in p]
        assert len(execute_paths) == 2

    def test_export_yaml_is_parseable(self, tmp_path):
        """The exported YAML should be parseable and match the JSON content."""
        catalog = _make_export_catalog()
        json_path, yaml_path = _export_openapi(catalog, tmp_path)

        with open(json_path) as f:
            json_spec = json.load(f)
        with open(yaml_path) as f:
            yaml_spec = yaml.safe_load(f)

        assert json_spec["openapi"] == yaml_spec["openapi"]
        assert json_spec["info"]["title"] == yaml_spec["info"]["title"]

    def test_export_filename_format(self, tmp_path):
        """Files should be named <package_name>_<version_name>.openapi.{json,yaml}."""
        catalog = _make_export_catalog()
        json_path, yaml_path = _export_openapi(catalog, tmp_path)

        assert json_path.name == "com.export.test_2.0.0.openapi.json"
        assert yaml_path.name == "com.export.test_2.0.0.openapi.yaml"
