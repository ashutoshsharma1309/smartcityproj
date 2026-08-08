"""Adapters for published vector layers (KML and GeoJSON).

These cover the Greater Chennai Corporation layers plus the Government of India
microwatershed map. They share the same shape: download a file, walk its
features, validate, upsert into PostGIS.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.data_ingestion.base import BaseDataSource, IngestionResult, SourceFeature
from app.services.data_ingestion.ckan import CKANClient
from app.services.data_ingestion.geometry import (
    Coordinate,
    GeometryError,
    linestring_wkt,
    multipolygon_wkt,
    polygon_wkt,
    validate_lonlat,
)
from app.services.data_ingestion.kml import iter_placemarks, merge_polygons
from app.services.data_ingestion.persistence import DIM_LINE, DIM_POLYGON, upsert_rows
from app.services.data_ingestion.validation import (
    require_geometry,
    require_within_bbox,
    run_rules,
)

logger = get_logger(__name__)


class CKANBackedSource(BaseDataSource):
    """Resolves its download URL through the CKAN API at run time."""

    async def resolve_url(self) -> str:
        access = self.config.get("access", {})
        if access.get("method") != "ckan":
            return await super().resolve_url()

        client = CKANClient(access["ckan_base_url"], timeout_seconds=self.timeout_seconds)
        return await client.resource_url(access["package_id"], access["resource_id"])


class WardBoundaryAdapter(CKANBackedSource):
    """GCC ward polygons -> ``zones`` with ``zone_type='ward'``.

    Wards are published as multi-part placemarks (200 placemarks holding 209
    polygons), so a placemark's polygons are merged into one MULTIPOLYGON — a
    ward is one zone however many disjoint pieces it has.
    """

    category = "administrative_boundary"
    zone_type = "ward"

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        for index, placemark in enumerate(iter_placemarks(payload)):
            if placemark.error:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason=placemark.error
                )
                continue

            wkt = merge_polygons(placemark.geometries)
            if wkt is None:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason="no_polygon_geometry"
                )
                continue

            # GCC identifies wards by number in <name>; `id_2` is an internal key.
            ward_number = (placemark.name or placemark.properties.get("name") or "").strip()
            external_id = ward_number or placemark.properties.get("id_2") or f"row-{index}"

            yield SourceFeature(
                external_id=str(external_id),
                properties={
                    "name": f"Ward {ward_number}" if ward_number else f"Zone {index}",
                    "raw": placemark.properties,
                },
                geometry_wkt=wkt,
                geometry_type="MultiPolygon",
            )

    def rules(self, bbox: list[float]) -> list[Any]:
        return [require_geometry, lambda f: require_within_bbox(f, bbox, margin=0.5)]

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        rows = [
            {
                "data_source_id": data_source_id,
                "city_id": city_id,
                "external_id": f.external_id,
                "name": f.properties["name"],
                "zone_type": self.zone_type,
                "geom_wkt": f.geometry_wkt,
            }
            for f in features
        ]
        written = await upsert_rows(
            session,
            table="zones",
            columns=["data_source_id", "city_id", "external_id", "name", "zone_type", "geom"],
            conflict_columns=["data_source_id", "external_id"],
            update_columns=["name", "zone_type"],
            rows=rows,
            geometry_dimension=DIM_POLYGON,
            geometry_multi=True,
        )
        result.records_written = written
        _account_for_unwritten(result, attempted=len(rows), written=written)


class WatershedAdapter(WardBoundaryAdapter):
    """GeoJSON microwatershed polygons -> ``zones`` with ``zone_type='watershed'``.

    Hydrologically these are the correct unit for flood analysis: water follows
    catchments, not ward lines.
    """

    category = "hydrology"
    zone_type = "watershed"

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        document = json.loads(payload.decode("utf-8"))
        features = document.get("features", []) if isinstance(document, dict) else []

        for index, feature in enumerate(features):
            geometry = feature.get("geometry") or {}
            properties = feature.get("properties") or {}
            try:
                wkt = _geojson_polygon_wkt(geometry)
            except GeometryError as exc:
                yield SourceFeature(external_id=None, properties={}, rejection_reason=str(exc))
                continue

            if wkt is None:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason="unsupported_geometry_type"
                )
                continue

            external_id = str(
                properties.get("id")
                or properties.get("OBJECTID")
                or properties.get("MWS_Code")
                or f"mws-{index}"
            )
            name = str(
                properties.get("name")
                or properties.get("MWS_Name")
                or f"Microwatershed {external_id}"
            )
            yield SourceFeature(
                external_id=external_id,
                properties={"name": name, "raw": properties},
                geometry_wkt=wkt,
                geometry_type="MultiPolygon",
            )


class WaterbodyAdapter(CKANBackedSource):
    """GCC waterbody polygons -> ``waterbodies``."""

    category = "hydrology"
    water_type = "waterbody"

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        for index, placemark in enumerate(iter_placemarks(payload)):
            if placemark.error:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason=placemark.error
                )
                continue

            wkt = merge_polygons(placemark.geometries)
            if wkt is None:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason="no_polygon_geometry"
                )
                continue

            yield SourceFeature(
                external_id=str(placemark.properties.get("OBJECTID") or f"wb-{index}"),
                properties={"name": placemark.name, "raw": placemark.properties},
                geometry_wkt=wkt,
                geometry_type="MultiPolygon",
            )

    def rules(self, bbox: list[float]) -> list[Any]:
        return [require_geometry, lambda f: require_within_bbox(f, bbox, margin=0.5)]

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        rows = [
            {
                "data_source_id": data_source_id,
                "city_id": city_id,
                "external_id": f.external_id,
                "name": (f.properties.get("name") or None),
                "water_type": self.water_type,
                "geom_wkt": f.geometry_wkt,
            }
            for f in features
        ]
        written = await upsert_rows(
            session,
            table="waterbodies",
            columns=["data_source_id", "city_id", "external_id", "name", "water_type", "geom"],
            conflict_columns=["data_source_id", "external_id"],
            update_columns=["name", "water_type"],
            rows=rows,
            geometry_dimension=DIM_POLYGON,
            geometry_multi=True,
        )
        result.records_written = written
        _account_for_unwritten(result, attempted=len(rows), written=written)


class LineLayerAdapter(CKANBackedSource):
    """Shared behaviour for KML line layers (roads, drains).

    A placemark may hold several LineStrings — the road layer has 20,407
    placemarks containing 36,922 lines — and each becomes its own row so that
    graph analysis sees real segments rather than merged multi-parts.
    """

    id_field: str = "OBJECTID"
    name_field: str | None = None

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        for index, placemark in enumerate(iter_placemarks(payload)):
            if placemark.error:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason=placemark.error
                )
                continue

            lines = [wkt for kind, wkt in placemark.geometries if kind == "LineString"]
            if not lines:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason="no_line_geometry"
                )
                continue

            base_id = str(placemark.properties.get(self.id_field) or f"row-{index}")
            name = placemark.properties.get(self.name_field) if self.name_field else placemark.name

            for part, wkt in enumerate(lines):
                yield SourceFeature(
                    # Multi-part placemarks need a per-part id or they would
                    # collide on the (source, external_id) unique constraint.
                    external_id=base_id if len(lines) == 1 else f"{base_id}-{part}",
                    properties={"name": name, "raw": placemark.properties},
                    geometry_wkt=wkt,
                    geometry_type="LineString",
                )

    def rules(self, bbox: list[float]) -> list[Any]:
        return [require_geometry, lambda f: require_within_bbox(f, bbox, margin=0.5)]


class RoadCenterlineAdapter(LineLayerAdapter):
    """GCC road centrelines -> ``road_segments``.

    The layer carries no road classification, so ``highway_class`` is stored as
    ``unclassified`` rather than guessed from the name. OpenStreetMap is
    ingested alongside to supply real classifications.
    """

    category = "road_network"
    id_field = "road_id"
    name_field = "road_name"

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        rows = [
            {
                "data_source_id": data_source_id,
                "city_id": city_id,
                "external_id": f.external_id,
                "name": (f.properties.get("name") or None),
                "highway_class": "unclassified",
                "is_bridge": False,
                "is_tunnel": False,
                "is_oneway": False,
                "geom_wkt": f.geometry_wkt,
            }
            for f in features
        ]
        written = await upsert_rows(
            session,
            table="road_segments",
            columns=[
                "data_source_id",
                "city_id",
                "external_id",
                "name",
                "highway_class",
                "is_bridge",
                "is_tunnel",
                "is_oneway",
                "geom",
            ],
            conflict_columns=["data_source_id", "external_id"],
            update_columns=["name", "highway_class"],
            rows=rows,
            geometry_dimension=DIM_LINE,
        )
        result.records_written = written
        _account_for_unwritten(result, attempted=len(rows), written=written)


class DrainageAdapter(LineLayerAdapter):
    """GCC storm water drains -> ``drainage_assets``.

    ``capacity_cumecs`` is left NULL: the source publishes geometry only.
    """

    category = "drainage"
    id_field = "OBJECTID"

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        rows = [
            {
                "data_source_id": data_source_id,
                "city_id": city_id,
                "external_id": f.external_id,
                "asset_type": "storm_drain",
                "name": (f.properties.get("name") or None),
                "notes": "Geometry only; the publisher records no hydraulic capacity.",
                "geom_wkt": f.geometry_wkt,
            }
            for f in features
        ]
        written = await upsert_rows(
            session,
            table="drainage_assets",
            columns=[
                "data_source_id",
                "city_id",
                "external_id",
                "asset_type",
                "name",
                "notes",
                "geom",
            ],
            conflict_columns=["data_source_id", "external_id"],
            update_columns=["asset_type", "name"],
            rows=rows,
            geometry_dimension=DIM_LINE,
        )
        result.records_written = written
        _account_for_unwritten(result, attempted=len(rows), written=written)


# ----------------------------------------------------------------- helpers
def _account_for_unwritten(result: IngestionResult, *, attempted: int, written: int) -> None:
    """Attribute rows that PostGIS refused so the report always balances."""
    shortfall = attempted - written
    if shortfall > 0:
        result.reject("geometry_invalid_after_repair", shortfall)
        result.records_valid = max(0, result.records_valid - shortfall)


def _ring(coordinates: list[list[float]]) -> list[Coordinate]:
    return [validate_lonlat(float(c[0]), float(c[1])) for c in coordinates if len(c) >= 2]


def _geojson_polygon_wkt(geometry: dict[str, Any]) -> str | None:
    """Convert a GeoJSON Polygon/MultiPolygon into MULTIPOLYGON WKT."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []

    if kind == "Polygon":
        if not coordinates:
            raise GeometryError("empty_coordinates")
        outer = _ring(coordinates[0])
        inners = [_ring(r) for r in coordinates[1:]]
        return multipolygon_wkt([polygon_wkt(outer, inners)])

    if kind == "MultiPolygon":
        polygons = []
        for polygon in coordinates:
            if not polygon:
                continue
            outer = _ring(polygon[0])
            inners = [_ring(r) for r in polygon[1:]]
            polygons.append(polygon_wkt(outer, inners))
        if not polygons:
            raise GeometryError("empty_coordinates")
        return multipolygon_wkt(polygons)

    return None


def _geojson_line_wkt(geometry: dict[str, Any]) -> str | None:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "LineString":
        return linestring_wkt(_ring(coordinates))
    return None


__all__ = [
    "CKANBackedSource",
    "DrainageAdapter",
    "LineLayerAdapter",
    "RoadCenterlineAdapter",
    "WardBoundaryAdapter",
    "WaterbodyAdapter",
    "WatershedAdapter",
    "run_rules",
]
