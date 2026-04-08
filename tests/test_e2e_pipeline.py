"""End-to-End pipeline tests — synthetic APK fixture through full pipeline.

Tests the complete static analysis pipeline:
  Fixture directory → IngestManifest → Parsers → Merger → ActionCatalog → OpenAPI → Gateway
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.extractor.src.ingest import ingest_from_decompiled
from apps.extractor.src.parsers import run_all_parsers
from packages.core_schema.models.action_catalog import ActionCatalog
from packages.core_schema.models.action_object import ActionObject
from packages.openapi_gen.src.generator import generate_openapi, generate_openapi_json, OpenAPIGenConfig
from packages.trace_model.src.merger import merge


# ═══════════════════════════════════════════════════════════════════════════════
# Fixture paths
# ═══════════════════════════════════════════════════════════════════════════════

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "apk" / "synthetic_apk"


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2EIngest:
    """Test APK ingestion from decompiled fixture directory."""

    def test_ingest_from_decompiled_directory(self):
        """Ingest the synthetic APK fixture and produce a valid IngestManifest."""
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))

        assert manifest.package_name == "com.shadow.test"
        assert manifest.version_name == "1.0.0"
        assert manifest.version_code == 1
        assert manifest.min_sdk == 26
        assert manifest.target_sdk == 34

    def test_ingest_discovers_smali_dirs(self):
        """The ingest should find the smali/ directory."""
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        assert len(manifest.smali_dirs) >= 1
        assert any("smali" in d for d in manifest.smali_dirs)

    def test_ingest_discovers_permissions(self):
        """Permissions from AndroidManifest.xml should be extracted."""
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        assert "android.permission.INTERNET" in manifest.uses_permissions
        assert "android.permission.ACCESS_NETWORK_STATE" in manifest.uses_permissions

    def test_ingest_discovers_components(self):
        """Activities and services should be extracted from the manifest."""
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        assert len(manifest.components) >= 2

        component_names = [c.name for c in manifest.components]
        assert "com.shadow.test.MainActivity" in component_names
        assert "com.shadow.test.LoginActivity" in component_names
        assert "com.shadow.test.SyncService" in component_names

    def test_ingest_main_activity_exported(self):
        """MainActivity should be marked as exported."""
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        main_activity = next(
            c for c in manifest.components if c.name == "com.shadow.test.MainActivity"
        )
        assert main_activity.exported is True
        assert main_activity.component_type == "activity"

    def test_ingest_intent_filters(self):
        """MainActivity should have MAIN/LAUNCHER intent filter."""
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        main_activity = next(
            c for c in manifest.components if c.name == "com.shadow.test.MainActivity"
        )
        assert len(main_activity.intent_filters) >= 1
        filter_data = main_activity.intent_filters[0]
        assert "android.intent.action.MAIN" in filter_data.get("actions", [])


class TestE2EStaticAnalysis:
    """Test running all static parsers on the synthetic fixture."""

    @pytest.fixture
    def manifest(self):
        return ingest_from_decompiled(str(FIXTURE_DIR))

    def test_parsers_produce_findings(self, manifest):
        """Running all parsers should produce at least one finding."""
        findings = run_all_parsers(manifest)
        assert len(findings) > 0

    def test_retrofit_parser_finds_endpoints(self, manifest):
        """The Retrofit parser should find endpoints in ApiService.smali."""
        findings = run_all_parsers(manifest)
        retrofit_findings = [f for f in findings if f.parser_name == "retrofit"]

        assert len(retrofit_findings) >= 3  # GET, POST, PUT, DELETE minus possible parsing quirks

        methods_found = {f.method for f in retrofit_findings}
        assert "GET" in methods_found
        assert "POST" in methods_found

    def test_okhttp_parser_finds_endpoints(self, manifest):
        """The OkHttp parser should find endpoints in HttpClient.smali."""
        findings = run_all_parsers(manifest)
        okhttp_findings = [f for f in findings if f.parser_name == "okhttp"]

        assert len(okhttp_findings) >= 1

        urls_found = [f.url_path for f in okhttp_findings]
        assert any("api.shadow.test" in u for u in urls_found)

    def test_retrofit_extracts_parameters(self, manifest):
        """The Retrofit parser should extract parameter annotations."""
        findings = run_all_parsers(manifest)
        retrofit_findings = [f for f in findings if f.parser_name == "retrofit"]

        # Find the login endpoint (POST /api/v1/auth/login)
        login_findings = [f for f in retrofit_findings if "login" in (f.url_path or "")]
        assert len(login_findings) >= 1

        login = login_findings[0]
        param_names = {p.name for p in login.parameters}
        assert "username" in param_names
        assert "password" in param_names

    def test_okhttp_extracts_headers(self, manifest):
        """The OkHttp parser should extract addHeader calls."""
        findings = run_all_parsers(manifest)
        okhttp_findings = [f for f in findings if f.parser_name == "okhttp"]

        # The HttpClient.smali has Authorization and X-Device-ID headers
        all_params = []
        for f in okhttp_findings:
            all_params.extend(f.parameters)

        header_names = {p.name for p in all_params if p.location == "header"}
        # At least Authorization should be found
        assert len(header_names) >= 1


class TestE2EMerge:
    """Test merging static findings into ActionCatalog."""

    @pytest.fixture
    def catalog(self):
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        findings = run_all_parsers(manifest)
        return merge(
            static_findings=findings,
            trace_records=[],
            package_name=manifest.package_name,
            version_name=manifest.version_name,
            version_code=manifest.version_code,
        )

    def test_merge_produces_catalog(self, catalog):
        """Merging should produce a valid ActionCatalog."""
        assert isinstance(catalog, ActionCatalog)
        assert catalog.package_name == "com.shadow.test"
        assert catalog.total_actions >= 3  # At least login, profile, and one OkHttp endpoint

    def test_catalog_actions_have_valid_ids(self, catalog):
        """Each action should have a non-empty action_id."""
        for action in catalog.actions:
            assert action.action_id
            assert len(action.action_id) > 0

    def test_catalog_actions_are_deduped(self, catalog):
        """No duplicate action_ids should exist."""
        action_ids = [a.action_id for a in catalog.actions]
        assert len(action_ids) == len(set(action_ids))

    def test_catalog_actions_have_confidence_scores(self, catalog):
        """Each action should have a confidence score between 0 and 1."""
        for action in catalog.actions:
            assert 0.0 <= action.confidence_score <= 1.0

    def test_catalog_actions_sorted_by_confidence(self, catalog):
        """Actions should be sorted by confidence descending."""
        scores = [a.confidence_score for a in catalog.actions]
        assert scores == sorted(scores, reverse=True)


class TestE2EOpenAPISpec:
    """Test generating OpenAPI spec from merged catalog."""

    @pytest.fixture
    def catalog(self):
        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        findings = run_all_parsers(manifest)
        return merge(
            static_findings=findings,
            trace_records=[],
            package_name=manifest.package_name,
            version_name=manifest.version_name,
            version_code=manifest.version_code,
        )

    def test_generate_openapi_spec(self, catalog):
        """OpenAPI spec should be generated from the merged catalog."""
        config = OpenAPIGenConfig(include_unapproved=True, min_confidence=0.0)
        spec = generate_openapi(catalog, config)

        assert spec["openapi"] == "3.1.0"
        assert "info" in spec
        assert "paths" in spec
        assert len(spec["paths"]) >= 1

    def test_openapi_spec_json_is_valid(self, catalog):
        """OpenAPI JSON should be parseable."""
        config = OpenAPIGenConfig(include_unapproved=True, min_confidence=0.0)
        json_str = generate_openapi_json(catalog, config)
        parsed = json.loads(json_str)
        assert parsed["openapi"] == "3.1.0"

    def test_openapi_spec_contains_actions(self, catalog):
        """OpenAPI spec should contain action execution paths."""
        config = OpenAPIGenConfig(include_unapproved=True, min_confidence=0.0)
        spec = generate_openapi(catalog, config)

        execute_paths = [p for p in spec["paths"] if "execute" in p]
        assert len(execute_paths) >= 1

    def test_openapi_spec_has_extension_fields(self, catalog):
        """OpenAPI spec should contain x-risk-tags and x-confidence extensions."""
        config = OpenAPIGenConfig(include_unapproved=True, min_confidence=0.0)
        spec = generate_openapi(catalog, config)

        execute_paths = [p for p in spec["paths"] if "execute" in p]
        if execute_paths:
            path_item = spec["paths"][execute_paths[0]]
            post_op = path_item.get("post", {})
            assert "x-confidence" in post_op
            assert "x-source" in post_op


class TestE2EGatewayIntegration:
    """Test serving the merged catalog through the FastAPI gateway."""

    @pytest.fixture
    def loaded_gateway(self):
        """Load the synthetic catalog into the gateway and return a test client."""
        from apps.gateway.src.main import app, _catalogs, load_catalog

        manifest = ingest_from_decompiled(str(FIXTURE_DIR))
        findings = run_all_parsers(manifest)
        catalog = merge(
            static_findings=findings,
            trace_records=[],
            package_name=manifest.package_name,
            version_name=manifest.version_name,
            version_code=manifest.version_code,
        )
        load_catalog(catalog)
        client = TestClient(app)
        yield client, catalog
        _catalogs.clear()

    def test_gateway_lists_loaded_app(self, loaded_gateway):
        """Gateway /apps endpoint should list the loaded app."""
        client, catalog = loaded_gateway
        res = client.get("/apps")
        assert res.status_code == 200
        apps = res.json()
        assert len(apps) >= 1
        assert any(a["package_name"] == "com.shadow.test" for a in apps)

    def test_gateway_lists_actions_for_app(self, loaded_gateway):
        """Gateway should list all discovered actions for the app."""
        client, catalog = loaded_gateway
        res = client.get(f"/apps/{catalog.app_id}/actions")
        assert res.status_code == 200
        actions = res.json()
        assert len(actions) >= 3

    def test_gateway_filters_by_confidence(self, loaded_gateway):
        """Gateway should filter actions by confidence threshold."""
        client, catalog = loaded_gateway
        res = client.get(f"/apps/{catalog.app_id}/actions?confidence_min=0.9")
        assert res.status_code == 200
        # All returned actions should have confidence >= 0.9
        for action in res.json():
            assert action["confidence_score"] >= 0.9

    def test_gateway_app_metadata(self, loaded_gateway):
        """Gateway should return app metadata."""
        client, catalog = loaded_gateway
        res = client.get(f"/apps/{catalog.app_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["package_name"] == "com.shadow.test"
        assert data["version_name"] == "1.0.0"

    def test_gateway_serves_openapi_spec(self, loaded_gateway):
        """Gateway should serve the OpenAPI spec for the app."""
        client, catalog = loaded_gateway
        res = client.get(f"/apps/{catalog.app_id}/spec.json")
        assert res.status_code == 200
        spec = res.json()
        assert spec["openapi"] == "3.1.0"
