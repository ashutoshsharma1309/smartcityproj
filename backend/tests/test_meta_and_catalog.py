"""The `/meta` and catalogue endpoints — the platform's honesty surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.registry import MODULES


def test_meta_lists_every_registered_module(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert {module["key"] for module in body["modules"]} == {module.key for module in MODULES}


def test_meta_reports_area_of_interest_from_configuration(client: TestClient) -> None:
    area = client.get("/api/v1/meta").json()["area_of_interest"]
    assert len(area["bbox"]) == 4
    min_lon, min_lat, max_lon, max_lat = area["bbox"]
    assert min_lon < max_lon and min_lat < max_lat
    assert len(area["center"]) == 2


def test_meta_reports_llm_as_unconfigured_without_credentials(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert body["llm_configured"] is False
    assert body["llm_provider"] == "none"


def test_unimplemented_modules_declare_a_planned_phase(client: TestClient) -> None:
    """An unimplemented module must say when it is coming, not just that it is missing."""
    for module in client.get("/api/v1/meta").json()["modules"]:
        if module["state"] != "implemented":
            assert module["planned_phase"], f"{module['key']} has no planned phase"


def test_catalog_summary_reports_zero_rather_than_omitting_counts(client: TestClient) -> None:
    """Zero counts are meaningful: they state that nothing has been ingested."""
    body = client.get("/api/v1/catalog/summary").json()
    assert body["zones"] == 0
    assert body["flood_incidents"] == 0
    assert set(body) == {
        "data_sources",
        "zones",
        "road_segments",
        "drainage_assets",
        "weather_observations",
        "tide_observations",
        "flood_incidents",
    }


def test_unknown_data_source_returns_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/catalog/sources/does-not-exist")
    assert response.status_code == 404

    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"]
