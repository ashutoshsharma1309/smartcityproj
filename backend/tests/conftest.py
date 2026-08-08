"""Shared pytest fixtures.

Unit tests run without any external service. The database session is replaced
with a fake through FastAPI's dependency overrides, so the whole HTTP surface —
routing, validation, error envelope, dependency wiring — is exercised in
milliseconds and in CI without Docker.

Tests that genuinely need PostGIS are marked ``integration`` and skipped unless
``URBANPULSE_TEST_DATABASE`` is set.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_cache_service, get_catalog_repository, get_geography_repository
from app.core.config import Settings, get_settings
from app.db.session import session_scope
from app.schemas.catalog import CatalogSummary
from app.schemas.common import GeoJSONFeatureCollection


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings isolated from the developer's local .env file."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        project_name="UrbanPulse",
        postgres_host="localhost",
        postgres_user="test",
        postgres_password="test",
        postgres_db="test",
        redis_enabled=False,
        llm_provider="none",
        llm_api_key=None,
        cors_origins=["http://localhost:3000"],
    )


class FakeCatalogRepository:
    """In-memory stand-in for :class:`~app.repositories.catalog.CatalogRepository`."""

    def __init__(self) -> None:
        self.sources: list[Any] = []

    async def list_data_sources(self, *, kind: Any = None, active_only: bool = False) -> list[Any]:
        return self.sources

    async def get_data_source_by_slug(self, slug: str) -> Any | None:
        return next((s for s in self.sources if s.slug == slug), None)

    async def list_ingestion_runs(self, *, limit: int = 50) -> list[Any]:
        return []

    async def summary(self) -> CatalogSummary:
        return CatalogSummary(
            data_sources=0,
            zones=0,
            road_segments=0,
            drainage_assets=0,
            weather_observations=0,
            tide_observations=0,
            flood_incidents=0,
        )


class FakeGeographyRepository:
    """Returns empty collections — the honest state before ingestion runs."""

    async def zones_as_geojson(self, **_: Any) -> GeoJSONFeatureCollection:
        return GeoJSONFeatureCollection(metadata={"count": 0, "srid": 4326, "limit": 1000})

    async def road_segments_as_geojson(self, **_: Any) -> GeoJSONFeatureCollection:
        return GeoJSONFeatureCollection(metadata={"count": 0, "srid": 4326, "limit": 5000})

    async def data_extent(self) -> list[float] | None:
        return None


class DisabledCacheService:
    """Cache facade with caching switched off; every read is a miss."""

    enabled = False

    async def get_json(self, key: str) -> Any | None:
        return None

    async def set_json(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        return None

    async def ping(self, *, timeout: float) -> None:
        raise RuntimeError("Cache is disabled.")

    async def invalidate_prefix(self, prefix: str) -> int:
        return 0


@pytest.fixture
def catalog_repository() -> FakeCatalogRepository:
    return FakeCatalogRepository()


@pytest.fixture
def app(settings: Settings, catalog_repository: FakeCatalogRepository) -> Iterator[FastAPI]:
    """Application instance with external dependencies overridden."""
    from app.main import create_app

    application = create_app(settings)

    async def _no_session() -> AsyncIterator[None]:
        yield None

    # Routes resolve settings through Depends(get_settings), which would
    # otherwise read the developer's local .env and make tests machine-dependent.
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[session_scope] = _no_session
    application.dependency_overrides[get_catalog_repository] = lambda: catalog_repository
    application.dependency_overrides[get_geography_repository] = FakeGeographyRepository
    application.dependency_overrides[get_cache_service] = DisabledCacheService

    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Test client that runs the lifespan, so startup wiring is covered too."""
    with TestClient(app) as test_client:
        yield test_client


def requires_database() -> bool:
    return bool(os.getenv("URBANPULSE_TEST_DATABASE"))
