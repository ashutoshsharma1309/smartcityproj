"""Risk, impact, recommendation and explanation contracts.

These schemas are the frozen interface between the ML pipeline and the UI. They
are defined now so the frontend, the model training code and the LLM prompt
templates are all written against the same shape. No endpoint returns these
yet — the risk engine ships in Phase 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import APIModel

RiskBand = Literal["low", "moderate", "high", "severe"]


class FeatureContribution(APIModel):
    """One driver of a prediction, taken from the model's SHAP values.

    Contributions come from the gradient-boosted model itself, never from the
    LLM. The LLM only paraphrases this list.
    """

    feature: str = Field(description="Feature name as used by the model.")
    display_name: str
    value: float | None = Field(description="The feature's value for this prediction.")
    unit: str | None = None
    #: Signed SHAP contribution in log-odds space; positive increases risk.
    contribution: float
    direction: Literal["increases_risk", "decreases_risk"]


class ZoneRiskPrediction(APIModel):
    zone_id: UUID
    zone_name: str
    #: Calibrated probability of waterlogging in the forecast window, 0.0-1.0.
    risk_probability: float = Field(ge=0.0, le=1.0)
    risk_band: RiskBand
    #: Width of the prediction interval; widens where input data is sparse.
    confidence: float = Field(ge=0.0, le=1.0)
    forecast_window_start: datetime
    forecast_window_end: datetime
    model_version: str
    #: Ordered by absolute contribution, largest first.
    top_contributions: list[FeatureContribution] = Field(default_factory=list)
    #: Names of inputs that were missing; the UI must show these as caveats.
    missing_inputs: list[str] = Field(default_factory=list)

    @field_validator("top_contributions")
    @classmethod
    def _limit_contributions(cls, value: list[FeatureContribution]) -> list[FeatureContribution]:
        return value[:10]


class RiskSurface(APIModel):
    """All zone predictions for one forecast run."""

    generated_at: datetime
    model_version: str
    forecast_window_start: datetime
    forecast_window_end: datetime
    predictions: list[ZoneRiskPrediction]


class AffectedRoad(APIModel):
    road_segment_id: UUID
    name: str | None
    highway_class: str
    #: Metres of this segment falling inside zones above the risk threshold.
    affected_length_m: float
    zone_risk_probability: float = Field(ge=0.0, le=1.0)
    is_bridge: bool
    is_tunnel: bool
    #: True when removing this segment disconnects the road graph, computed
    #: with NetworkX rather than assumed from road class.
    is_critical_link: bool


class ImpactAssessment(APIModel):
    generated_at: datetime
    risk_threshold: float = Field(ge=0.0, le=1.0)
    affected_roads: list[AffectedRoad]
    total_affected_length_km: float
    affected_zone_count: int
    #: Zones whose road access is fully severed at this threshold.
    isolated_zone_ids: list[UUID] = Field(default_factory=list)
    estimated_population_affected: int | None = Field(
        default=None,
        description="Null when zone population data has not been ingested.",
    )


ActionPriority = Literal["immediate", "within_6h", "within_24h", "preventive"]


class RecommendedAction(APIModel):
    """A municipal action produced by the deterministic rules engine.

    Each action names the rule that fired and the evidence that triggered it,
    so an operator can audit why it was suggested.
    """

    action_id: str
    title: str
    priority: ActionPriority
    #: Department or unit expected to act, e.g. "storm_water_drainage".
    responsible_unit: str
    rationale: str
    triggering_rule: str
    zone_ids: list[UUID] = Field(default_factory=list)
    road_segment_ids: list[UUID] = Field(default_factory=list)


class ExplanationRequest(APIModel):
    """Input to the LLM explanation service.

    The payload carries only facts already computed by the pipeline. The
    service refuses to call the provider if the prediction is absent.
    """

    prediction: ZoneRiskPrediction
    impact: ImpactAssessment | None = None
    actions: list[RecommendedAction] = Field(default_factory=list)
    audience: Literal["operator", "public"] = "operator"
    max_words: int = Field(default=120, ge=40, le=400)


class ExplanationResponse(APIModel):
    summary: str
    audience: Literal["operator", "public"]
    #: Provider and model that produced the text, for auditability.
    provider: str
    model: str
    generated_at: datetime
    #: Echoes the facts handed to the model so the output can be checked.
    grounded_on: dict[str, object] = Field(default_factory=dict)
