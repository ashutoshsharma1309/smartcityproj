"""Geospatial reads.

Geometry is serialised to GeoJSON inside PostgreSQL with ``ST_AsGeoJSON`` so
the API process never needs GEOS bindings. The heavy geometry libraries
(GeoPandas, Shapely) belong to the offline pipeline, keeping the API image small.
"""

from __future__ import annotations

import json

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.geography import SRID, RoadSegment, Zone
from app.schemas.common import GeoJSONFeature, GeoJSONFeatureCollection

#: Douglas-Peucker tolerance in degrees, applied server-side so large wards do
#: not ship megabytes of vertices to the browser. ~11 m at the equator.
DEFAULT_SIMPLIFY_TOLERANCE_DEG = 0.0001


class GeographyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def zones_as_geojson(
        self,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
        simplify_tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE_DEG,
    ) -> GeoJSONFeatureCollection:
        geom = func.ST_SimplifyPreserveTopology(Zone.geom, simplify_tolerance)
        stmt = select(
            Zone.id,
            Zone.external_id,
            Zone.name,
            Zone.zone_type,
            Zone.area_sq_km,
            Zone.mean_elevation_m,
            Zone.mean_slope_deg,
            Zone.impervious_fraction,
            Zone.population,
            func.ST_AsGeoJSON(geom).label("geometry"),
        ).limit(limit)

        if bbox is not None:
            stmt = stmt.where(Zone.geom.intersects(func.ST_MakeEnvelope(*bbox, SRID)))

        rows = (await self._session.execute(stmt)).all()
        features = [
            GeoJSONFeature(
                id=str(row.id),
                geometry=json.loads(row.geometry),
                properties={
                    "external_id": row.external_id,
                    "name": row.name,
                    "zone_type": row.zone_type,
                    "area_sq_km": row.area_sq_km,
                    "mean_elevation_m": row.mean_elevation_m,
                    "mean_slope_deg": row.mean_slope_deg,
                    "impervious_fraction": row.impervious_fraction,
                    "population": row.population,
                },
            )
            for row in rows
        ]
        return GeoJSONFeatureCollection(
            features=features,
            metadata={"count": len(features), "srid": SRID, "limit": limit},
        )

    async def road_segments_as_geojson(
        self,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        highway_classes: list[str] | None = None,
        limit: int = 5000,
    ) -> GeoJSONFeatureCollection:
        stmt = select(
            RoadSegment.id,
            RoadSegment.osm_id,
            RoadSegment.name,
            RoadSegment.highway_class,
            RoadSegment.is_bridge,
            RoadSegment.is_tunnel,
            RoadSegment.length_m,
            func.ST_AsGeoJSON(RoadSegment.geom).label("geometry"),
        ).limit(limit)

        if bbox is not None:
            stmt = stmt.where(RoadSegment.geom.intersects(func.ST_MakeEnvelope(*bbox, SRID)))
        if highway_classes:
            stmt = stmt.where(RoadSegment.highway_class.in_(highway_classes))

        rows = (await self._session.execute(stmt)).all()
        features = [
            GeoJSONFeature(
                id=str(row.id),
                geometry=json.loads(row.geometry),
                properties={
                    "osm_id": row.osm_id,
                    "name": row.name,
                    "highway_class": row.highway_class,
                    "is_bridge": row.is_bridge,
                    "is_tunnel": row.is_tunnel,
                    "length_m": row.length_m,
                },
            )
            for row in rows
        ]
        return GeoJSONFeatureCollection(
            features=features,
            metadata={"count": len(features), "srid": SRID, "limit": limit},
        )

    async def data_extent(self) -> list[float] | None:
        """Bounding box of all ingested zones, or None when no zones exist.

        The frontend uses this to fit the map to real data instead of assuming
        the configured city bounds are populated.
        """
        stmt = select(
            func.ST_XMin(func.ST_Extent(Zone.geom)).cast(Float),
            func.ST_YMin(func.ST_Extent(Zone.geom)).cast(Float),
            func.ST_XMax(func.ST_Extent(Zone.geom)).cast(Float),
            func.ST_YMax(func.ST_Extent(Zone.geom)).cast(Float),
        )
        row = (await self._session.execute(stmt)).one()
        if row[0] is None:
            return None
        return [float(v) for v in row]
