"""Tests for the quickstart example catalog."""

import json
from pathlib import Path

from packages.core_schema.models.action_catalog import ActionCatalog


QUICKSTART_CATALOG = Path(__file__).resolve().parent.parent / "examples" / "quickstart" / "catalog.json"


class TestQuickstartExample:
    """Validate the quickstart example catalog against the schema."""

    def test_catalog_file_exists(self):
        """The quickstart catalog.json should exist."""
        assert QUICKSTART_CATALOG.exists(), f"Missing: {QUICKSTART_CATALOG}"

    def test_catalog_validates_against_schema(self):
        """The catalog should pass Pydantic validation."""
        with open(QUICKSTART_CATALOG) as f:
            data = json.load(f)

        catalog = ActionCatalog.model_validate(data)
        assert catalog.app_id == "quickstart-demo"
        assert catalog.package_name == "com.example.quickstart"

    def test_catalog_has_three_actions(self):
        """The quickstart catalog should have exactly 3 actions."""
        with open(QUICKSTART_CATALOG) as f:
            data = json.load(f)

        catalog = ActionCatalog.model_validate(data)
        assert len(catalog.actions) == 3

    def test_catalog_has_approved_and_unapproved(self):
        """The catalog should have at least one approved and one unapproved action."""
        with open(QUICKSTART_CATALOG) as f:
            data = json.load(f)

        catalog = ActionCatalog.model_validate(data)
        approved = [a for a in catalog.actions if a.approved]
        unapproved = [a for a in catalog.actions if not a.approved]

        assert len(approved) >= 1, "Should have at least one approved action"
        assert len(unapproved) >= 1, "Should have at least one unapproved action"

    def test_catalog_has_high_and_low_confidence(self):
        """Should have actions with high (>=0.75) and low (<0.4) confidence."""
        with open(QUICKSTART_CATALOG) as f:
            data = json.load(f)

        catalog = ActionCatalog.model_validate(data)
        high = [a for a in catalog.actions if a.confidence_score >= 0.75]
        low = [a for a in catalog.actions if a.confidence_score < 0.40]

        assert len(high) >= 1, "Should have at least one high-confidence action"
        assert len(low) >= 1, "Should have at least one low-confidence action"
