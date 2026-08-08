"""The LLM prompt must contain every fact and invent none.

These are pure-function tests over the prompt builder — no network, no provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.schemas.risk import (
    AffectedRoad,
    ExplanationRequest,
    FeatureContribution,
    ImpactAssessment,
    ZoneRiskPrediction,
)
from app.services.llm.prompts import SYSTEM_PROMPT, build_user_prompt, grounding_payload
from app.services.llm.provider import CompletionRequest, NullLLMProvider


def _prediction(**overrides) -> ZoneRiskPrediction:
    start = datetime(2026, 7, 12, 6, 0, tzinfo=UTC)
    defaults = {
        "zone_id": uuid4(),
        "zone_name": "Kurla West",
        "risk_probability": 0.73,
        "risk_band": "high",
        "confidence": 0.61,
        "forecast_window_start": start,
        "forecast_window_end": start + timedelta(hours=6),
        "model_version": "lgbm-2026.07.1",
        "top_contributions": [
            FeatureContribution(
                feature="rain_24h_mm",
                display_name="Rainfall in the last 24 hours",
                value=118.0,
                unit="mm",
                contribution=1.42,
                direction="increases_risk",
            ),
            FeatureContribution(
                feature="mean_slope_deg",
                display_name="Mean terrain slope",
                value=0.8,
                unit="degrees",
                contribution=-0.31,
                direction="decreases_risk",
            ),
        ],
        "missing_inputs": ["storm_drain_capacity"],
    }
    return ZoneRiskPrediction(**{**defaults, **overrides})


def test_prompt_contains_every_supplied_number() -> None:
    prompt = build_user_prompt(ExplanationRequest(prediction=_prediction()))
    assert "Kurla West" in prompt
    assert "73%" in prompt
    assert "high" in prompt
    assert "118" in prompt
    assert "lgbm-2026.07.1" in prompt


def test_prompt_states_missing_inputs_explicitly() -> None:
    """Silently omitting a missing input would let the model imply it was fine."""
    prompt = build_user_prompt(ExplanationRequest(prediction=_prediction()))
    assert "unavailable for this prediction" in prompt
    assert "storm_drain_capacity" in prompt


def test_prompt_marks_contribution_direction() -> None:
    prompt = build_user_prompt(ExplanationRequest(prediction=_prediction()))
    assert "increases risk" in prompt
    assert "decreases risk" in prompt


def test_prompt_says_population_is_unavailable_rather_than_guessing() -> None:
    impact = ImpactAssessment(
        generated_at=datetime.now(UTC),
        risk_threshold=0.5,
        affected_roads=[
            AffectedRoad(
                road_segment_id=uuid4(),
                name="LBS Marg",
                highway_class="primary",
                affected_length_m=820.0,
                zone_risk_probability=0.73,
                is_bridge=False,
                is_tunnel=False,
                is_critical_link=True,
            )
        ],
        total_affected_length_km=0.82,
        affected_zone_count=1,
        isolated_zone_ids=[],
        estimated_population_affected=None,
    )
    prompt = build_user_prompt(ExplanationRequest(prediction=_prediction(), impact=impact))
    assert "Estimated population affected: not available" in prompt
    assert "LBS Marg" in prompt
    assert "Critical links" in prompt


def test_system_prompt_forbids_inventing_values() -> None:
    assert "only the numbers" in SYSTEM_PROMPT
    assert "Never introduce a value" in SYSTEM_PROMPT


def test_contributions_are_capped_at_ten() -> None:
    """Keeps the prompt bounded regardless of model feature count."""
    many = [
        FeatureContribution(
            feature=f"f{i}",
            display_name=f"Feature {i}",
            value=float(i),
            unit=None,
            contribution=0.1,
            direction="increases_risk",
        )
        for i in range(25)
    ]
    assert len(_prediction(top_contributions=many).top_contributions) == 10


def test_grounding_payload_echoes_auditable_facts() -> None:
    prediction = _prediction()
    payload = grounding_payload(ExplanationRequest(prediction=prediction))
    assert payload["risk_probability"] == prediction.risk_probability
    assert payload["model_version"] == prediction.model_version
    assert payload["missing_inputs"] == ["storm_drain_capacity"]


async def test_null_provider_refuses_instead_of_returning_text() -> None:
    from app.core.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError):
        await NullLLMProvider().complete(
            CompletionRequest(system_prompt="s", user_prompt="u", max_output_tokens=10)
        )


def test_probability_bounds_are_enforced_by_the_schema() -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        _prediction(risk_probability=1.4)
