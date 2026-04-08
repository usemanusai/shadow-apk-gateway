"""Confidence Scorer — Assigns confidence scores to ActionObjects.

Uses a rule-based scoring system with adjustments based on evidence quality.
"""

from __future__ import annotations


def compute_confidence_score(
    has_static: bool = False,
    has_dynamic: bool = False,
    url_templates_agree: bool = False,
    has_200_response: bool = False,
    url_has_opaque_hash: bool = False,
    is_static_only_with_concat: bool = False,
    has_native_in_stack: bool = False,
    long_path: bool = False,
) -> float:
    """Compute confidence score for an action based on evidence signals.

    Scoring table:
    - Dynamic trace exists:               +0.40
    - Static finding exists:              +0.25
    - Both agree on URL template:         +0.15
    - Response body captured (200):       +0.10
    - URL has opaque hash / >3 segments:  -0.10
    - Static-only with string concat:     -0.15
    - Native library in call stack:       -0.20

    Final score clamped to [0.0, 1.0].
    """
    score = 0.0

    # Positive signals
    if has_dynamic:
        score += 0.40
    if has_static:
        score += 0.25
    if url_templates_agree:
        score += 0.15
    if has_200_response:
        score += 0.10

    # Negative signals
    if url_has_opaque_hash or long_path:
        score -= 0.10
    if is_static_only_with_concat:
        score -= 0.15
    if has_native_in_stack:
        score -= 0.20

    # Clamp
    return max(0.0, min(1.0, round(score, 2)))


def score_label(score: float) -> str:
    """Return a human-readable label for a confidence score."""
    if score >= 0.75:
        return "high"
    elif score >= 0.40:
        return "medium"
    else:
        return "low"
