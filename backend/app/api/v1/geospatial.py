"""Geospatial endpoints serving RFC 7946 GeoJSON for MapLibre."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import BBoxDep, GeospatialServiceDep
from app.schemas.common import GeoJSONFeatureCollection

router = APIRouter(prefix="/geo", tags=["geospatial"])


@router.get(
    "/zones",
    response_model=GeoJSONFeatureCollection,
    summary="Analysis zones as GeoJSON",
    description=(
        "Zone polygons with their derived terrain attributes. Geometry is simplified inside "
        "PostGIS before transfer. Returns an empty collection until boundary data is ingested."
    ),
)
async def get_zones(service: GeospatialServiceDep, bbox: BBoxDep) -> GeoJSONFeatureCollection:
    return await service.zones(bbox=bbox)


@router.get(
    "/roads",
    response_model=GeoJSONFeatureCollection,
    summary="Road segments as GeoJSON",
    description=(
        "OpenStreetMap-derived road centrelines. Returns an empty collection until the road "
        "network is ingested."
    ),
)
async def get_roads(service: GeospatialServiceDep, bbox: BBoxDep) -> GeoJSONFeatureCollection:
    return await service.road_network(bbox=bbox)


@router.get(
    "/extent",
    summary="Bounding box of ingested geometry",
    description=(
        "Extent of all stored zones, or null when none exist. Lets the client fit the map to "
        "real data instead of assuming the configured city bounds are populated."
    ),
)
async def get_extent(service: GeospatialServiceDep) -> dict[str, list[float] | None]:
    return {"bbox": await service.data_extent()}
