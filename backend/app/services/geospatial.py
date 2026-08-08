"""Geospatial processing service.

Read paths are implemented against PostGIS. Terrain derivation is not: it needs
a DEM raster that has not been ingested, so it raises rather than returning
plausible-looking numbers.
"""

from __future__ import annotations

from uuid import UUID

from app.cache.redis_cache import CacheService
from app.core.exceptions import NotImplementedFeatureError
from app.repositories.geography import GeographyRepository
from app.schemas.common import GeoJSONFeatureCollection

CACHE_PREFIX = "geo:"


def _bbox_key(kind: str, bbox: tuple[float, float, float, float] | None) -> str:
    if bbox is None:
        return f"{CACHE_PREFIX}{kind}:all"
    return f"{CACHE_PREFIX}{kind}:" + ",".join(f"{v:.4f}" for v in bbox)


class PostGISGeospatialService:
    """Implements :class:`~app.services.interfaces.GeospatialService`."""

    def __init__(self, repository: GeographyRepository, cache: CacheService) -> None:
        self._repository = repository
        self._cache = cache

    async def zones(
        self, *, bbox: tuple[float, float, float, float] | None = None
    ) -> GeoJSONFeatureCollection:
        key = _bbox_key("zones", bbox)
        cached = await self._cache.get_json(key)
        if cached is not None:
            return GeoJSONFeatureCollection.model_validate(cached)

        collection = await self._repository.zones_as_geojson(bbox=bbox)
        await self._cache.set_json(key, collection.model_dump(mode="json"))
        return collection

    async def road_network(
        self, *, bbox: tuple[float, float, float, float] | None = None
    ) -> GeoJSONFeatureCollection:
        key = _bbox_key("roads", bbox)
        cached = await self._cache.get_json(key)
        if cached is not None:
            return GeoJSONFeatureCollection.model_validate(cached)

        collection = await self._repository.road_segments_as_geojson(bbox=bbox)
        await self._cache.set_json(key, collection.model_dump(mode="json"))
        return collection

    async def data_extent(self) -> list[float] | None:
        return await self._repository.data_extent()

    async def derive_terrain_attributes(self, zone_id: UUID) -> None:
        raise NotImplementedFeatureError(
            "Terrain attribute derivation requires a digital elevation model that has not "
            "been ingested for the configured city.",
            module="geospatial",
            planned_phase="Phase 2",
        )
