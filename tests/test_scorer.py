"""Tests for the confidence scorer."""

import pytest
from packages.trace_model.src.scorer import compute_confidence_score, score_label


class TestConfidenceScorer:
    """Test the rule-based confidence scoring system."""

    def test_dynamic_only_score(self):
        """Dynamic trace exists → +0.40."""
        score = compute_confidence_score(has_dynamic=True)
        assert score == 0.40

    def test_static_only_score(self):
        """Static finding exists → +0.25."""
        score = compute_confidence_score(has_static=True)
        assert score == 0.25

    def test_merged_agreement(self):
        """Both sources agree → high confidence."""
        score = compute_confidence_score(
            has_static=True,
            has_dynamic=True,
            url_templates_agree=True,
            has_200_response=True,
        )
        # 0.25 + 0.40 + 0.15 + 0.10 = 0.90
        assert score == 0.90

    def test_negative_signals(self):
        """Negative signals reduce confidence."""
        # Static only with concat: 0.25 - 0.15 = 0.10
        score = compute_confidence_score(
            has_static=True,
            is_static_only_with_concat=True,
        )
        assert score == 0.10

    def test_native_penalty(self):
        """Native library in call stack → -0.20."""
        score = compute_confidence_score(
            has_dynamic=True,
            has_native_in_stack=True,
        )
        # 0.40 - 0.20 = 0.20
        assert score == 0.20

    def test_clamp_to_zero(self):
        """Score should not go below 0.0."""
        score = compute_confidence_score(
            has_native_in_stack=True,
            url_has_opaque_hash=True,
        )
        assert score == 0.0

    def test_clamp_to_one(self):
        """Score should not exceed 1.0."""
        score = compute_confidence_score(
            has_static=True,
            has_dynamic=True,
            url_templates_agree=True,
            has_200_response=True,
        )
        assert score <= 1.0

    def test_score_labels(self):
        assert score_label(0.90) == "high"
        assert score_label(0.75) == "high"
        assert score_label(0.60) == "medium"
        assert score_label(0.40) == "medium"
        assert score_label(0.30) == "low"
        assert score_label(0.00) == "low"
