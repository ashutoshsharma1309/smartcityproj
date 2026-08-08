"""Configuration validation, CORS, and geospatial request handling."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import parse_bbox
from app.core.config import Settings
from app.core.exceptions import ValidationError


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "postgres_user": "u",
        "postgres_password": "p",
        "postgres_db": "d",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_database_urls_use_the_expected_drivers() -> None:
    settings = _settings(postgres_host="db", postgres_port=5433)
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.sync_database_url.startswith("postgresql+psycopg://")
    assert "db:5433" in settings.database_url


def test_llm_is_not_considered_configured_without_a_key() -> None:
    assert _settings(llm_provider="openai", llm_api_key=None).llm_configured is False
    assert _settings(llm_provider="openai", llm_api_key="sk-test").llm_configured is True
    assert _settings(llm_provider="none", llm_api_key="sk-test").llm_configured is False


def test_list_settings_accept_comma_separated_strings() -> None:
    settings = _settings(cors_origins="http://a.test,http://b.test")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_invalid_bbox_configuration_is_rejected_at_startup() -> None:
    with pytest.raises(PydanticValidationError):
        _settings(city_bbox=[10.0, 20.0, 5.0, 30.0])  # min_lon >= max_lon
    with pytest.raises(PydanticValidationError):
        _settings(city_bbox=[10.0, 20.0, 30.0])  # wrong length


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        _settings(log_level="CHATTY")


# ------------------------------------------------------------------ bbox parsing
def test_parse_bbox_accepts_a_valid_viewport() -> None:
    assert parse_bbox("72.7,18.8,73.0,19.3") == (72.7, 18.8, 73.0, 19.3)


def test_parse_bbox_returns_none_when_absent() -> None:
    assert parse_bbox(None) is None


@pytest.mark.parametrize(
    "value",
    [
        "1,2,3",  # too few values
        "a,b,c,d",  # non-numeric
        "73.0,18.8,72.7,19.3",  # min_lon > max_lon
        "72.7,19.3,73.0,18.8",  # min_lat > max_lat
        "-200,18.8,73.0,19.3",  # out of range
    ],
)
def test_parse_bbox_rejects_malformed_input(value: str) -> None:
    with pytest.raises(ValidationError):
        parse_bbox(value)


# ------------------------------------------------------------------- geo routes
def test_zones_return_an_empty_feature_collection_before_ingestion(
    client: TestClient,
) -> None:
    """An empty FeatureCollection is the correct answer, not an error."""
    body = client.get("/api/v1/geo/zones").json()
    assert body["type"] == "FeatureCollection"
    assert body["features"] == []
    assert body["metadata"]["count"] == 0


def test_extent_is_null_when_no_geometry_exists(client: TestClient) -> None:
    assert client.get("/api/v1/geo/extent").json() == {"bbox": None}


def test_bad_bbox_query_returns_422_with_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/geo/zones", params={"bbox": "not,a,bbox,here"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------------------- cors
def test_cors_allows_the_configured_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/meta",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_an_unlisted_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/meta",
        headers={
            "Origin": "http://evil.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_openapi_document_is_generated(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "UrbanPulse"
    assert "/api/v1/meta" in schema["paths"]
    assert "/health/db" in schema["paths"]
