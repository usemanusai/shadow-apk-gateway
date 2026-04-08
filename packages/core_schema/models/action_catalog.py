"""ActionCatalog — Layer 4 output schema.

Container for a complete set of ActionObjects discovered for a single app.
This is the primary input to the OpenAPI generator and the gateway.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.core_schema.models.action_object import ActionObject


class ActionCatalog(BaseModel):
    """Complete catalog of discovered API actions for an Android application."""

    model_config = ConfigDict(populate_by_name=True)

    # App identity
    app_id: str = Field(description="Unique identifier for this analysis run")
    package_name: str
    version_name: str
    version_code: int

    # Analysis metadata
    analysis_timestamp: Optional[str] = None
    static_finding_count: int = 0
    trace_record_count: int = 0

    # The primary payload
    actions: list[ActionObject] = Field(default_factory=list)

    # Summary statistics
    @property
    def total_actions(self) -> int:
        return len(self.actions)

    @property
    def approved_actions(self) -> int:
        return sum(1 for a in self.actions if a.approved)

    @property
    def high_confidence_actions(self) -> int:
        return sum(1 for a in self.actions if a.confidence_score >= 0.75)

    @property
    def actions_needing_review(self) -> int:
        return sum(1 for a in self.actions if a.confidence_score < 0.40)

    def get_action(self, action_id: str) -> Optional[ActionObject]:
        """Look up an action by its ID."""
        for action in self.actions:
            if action.action_id == action_id:
                return action
        return None

    def get_approved_actions(self, min_confidence: float = 0.6) -> list[ActionObject]:
        """Return actions that are approved and above the confidence threshold."""
        return [
            a
            for a in self.actions
            if a.approved and a.confidence_score >= min_confidence
        ]
