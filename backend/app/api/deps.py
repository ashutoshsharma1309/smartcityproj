"""FastAPI dependency wiring.

Services are constructed per request from their collaborators. Routes depend on
the annotated aliases here rather than importing concrete classes, so an
implementation can be swapped (or faked in a test) in one place.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import CacheService, get_cache
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationError
from app.db.session import session_scope
from app.repositories.catalog import CatalogRepository
from app.repositories.geography import GeographyRepository
from app.services.geospatial import PostGISGeospatialService
from app.services.llm.explanation import GroundedExplanationService
from app.services.llm.provider import build_provider
from app.services.pipeline_stubs import (
    UnimplementedImpactService,
    UnimplementedIngestionService,
    UnimplementedPredictionService,
    UnimplementedRecommendationService,
)

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(session_scope)]


def get_cache_service(settings: SettingsDep) -> CacheService:
    return CacheService(get_cache(), default_ttl=settings.cache_default_ttl_seconds)


CacheDep = Annotated[CacheService, Depends(get_cache_service)]


def get_catalog_repository(session: SessionDep) -> CatalogRepository:
    return CatalogRepository(session)


def get_geography_repository(session: SessionDep) -> GeographyRepository:
    return GeographyRepository(session)


CatalogRepositoryDep = Annotated[CatalogRepository, Depends(get_catalog_repository)]
GeographyRepositoryDep = Annotated[GeographyRepository, Depends(get_geography_repository)]


def get_geospatial_service(
    repository: GeographyRepositoryDep, cache: CacheDep
) -> PostGISGeospatialService:
    return PostGISGeospatialService(repository, cache)


def get_ingestion_service() -> UnimplementedIngestionService:
    return UnimplementedIngestionService()


def get_prediction_service() -> UnimplementedPredictionService:
    return UnimplementedPredictionService()


def get_impact_service() -> UnimplementedImpactService:
    return UnimplementedImpactService()


def get_recommendation_service() -> UnimplementedRecommendationService:
    return UnimplementedRecommendationService()


def get_explanation_service(settings: SettingsDep) -> GroundedExplanationService:
    return GroundedExplanationService(build_provider(settings), settings)


GeospatialServiceDep = Annotated[PostGISGeospatialService, Depends(get_geospatial_service)]
IngestionServiceDep = Annotated[UnimplementedIngestionService, Depends(get_ingestion_service)]
PredictionServiceDep = Annotated[UnimplementedPredictionService, Depends(get_prediction_service)]
ImpactServiceDep = Annotated[UnimplementedImpactService, Depends(get_impact_service)]
RecommendationServiceDep = Annotated[
    UnimplementedRecommendationService, Depends(get_recommendation_service)
]
ExplanationServiceDep = Annotated[GroundedExplanationService, Depends(get_explanation_service)]


def parse_bbox(
    bbox: Annotated[
        str | None,
        Query(
            description=(
                "Viewport filter as 'min_lon,min_lat,max_lon,max_lat' in EPSG:4326. "
                "Omit to return everything up to the endpoint limit."
            ),
            examples=["72.775,18.890,72.990,19.280"],
        ),
    ] = None,
) -> tuple[float, float, float, float] | None:
    """Validate a bbox query parameter into an ordered tuple."""
    if bbox is None:
        return None

    parts = [part.strip() for part in bbox.split(",")]
    if len(parts) != 4:
        raise ValidationError("bbox must contain exactly four comma-separated numbers.")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as exc:
        raise ValidationError("bbox values must be numeric.") from exc

    if not (-180 <= min_lon < max_lon <= 180):
        raise ValidationError("bbox longitudes must satisfy -180 <= min_lon < max_lon <= 180.")
    if not (-90 <= min_lat < max_lat <= 90):
        raise ValidationError("bbox latitudes must satisfy -90 <= min_lat < max_lat <= 90.")

    return (min_lon, min_lat, max_lon, max_lat)


BBoxDep = Annotated[tuple[float, float, float, float] | None, Depends(parse_bbox)]
