"""Unimplemented analysis endpoints must fail loudly, never plausibly.

These tests encode the product's central rule: a capability that does not exist
returns 501 naming the module and phase. If someone later replaces a stub with
hardcoded sample output to make a demo look complete, these tests break.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ZONE_ID = str(uuid4())


def _empty_surface() -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "generated_at": now,
        "model_version": "unavailable",
        "forecast_window_start": now,
        "forecast_window_end": now,
        "predictions": [],
    }


def _empty_impact() -> dict:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "risk_threshold": 0.5,
        "affected_roads": [],
        "total_affected_length_km": 0.0,
        "affected_zone_count": 0,
        "isolated_zone_ids": [],
        "estimated_population_affected": None,
    }


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", f"/api/v1/risk/zones/{ZONE_ID}", None),
        ("get", "/api/v1/risk/surface", None),
        ("post", "/api/v1/ingestion/open-meteo-archive/run", None),
        ("post", "/api/v1/impact/assess", {"surface": _empty_surface()}),
        (
            "post",
            "/api/v1/recommendations",
            {"surface": _empty_surface(), "impact": _empty_impact()},
        ),
    ],
)
def test_unimplemented_endpoints_return_501(
    client: TestClient, method: str, path: str, payload: dict | None
) -> None:
    call = getattr(client, method)
    response = call(path, json=payload) if payload else call(path)
    assert response.status_code == 501, response.text

    error = response.json()["error"]
    assert error["code"] == "not_implemented"
    assert error["details"]["module"]
    assert error["details"]["planned_phase"]


def test_risk_endpoint_never_returns_a_probability(client: TestClient) -> None:
    """The failure mode this guards against is a stub returning 0.0 as 'no risk'."""
    body = client.get(f"/api/v1/risk/zones/{ZONE_ID}").json()
    assert "risk_probability" not in body
    assert "error" in body


def test_explain_reports_missing_llm_configuration(client: TestClient) -> None:
    """With no provider configured the service refuses rather than writing filler."""
    now = datetime.now(UTC).isoformat()
    payload = {
        "prediction": {
            "zone_id": ZONE_ID,
            "zone_name": "Test Ward",
            "risk_probability": 0.72,
            "risk_band": "high",
            "confidence": 0.6,
            "forecast_window_start": now,
            "forecast_window_end": now,
            "model_version": "test-1",
            "top_contributions": [],
            "missing_inputs": [],
        },
        "audience": "operator",
        "max_words": 80,
    }
    response = client.post("/api/v1/explain", json=payload)
    assert response.status_code == 500

    error = response.json()["error"]
    assert error["code"] == "configuration_error"
    assert "LLM_API_KEY" in error["details"]["required_env"]


def test_validation_failure_uses_the_shared_error_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/explain", json={"prediction": {"zone_name": "x"}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
