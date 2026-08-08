"""Flood observation adapters — the supervised labels for Phase 3.

Two record types land in ``flood_incidents`` and must not be conflated:

* :class:`InundationPointAdapter` reads locations with a measured depth but no
  date. That is a *spatial susceptibility* label.
* :class:`FloodEventPointAdapter` reads locations flooded during a named, dated
  event. That is an *event observation*.

The date on an event comes from the catalogue configuration (the dataset is
published as "2015 floods"), never inferred from the geometry or the file.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.observations import FloodRecordType, IncidentSeverity
from app.services.data_ingestion.adapters.vector import CKANBackedSource, _account_for_unwritten
from app.services.data_ingestion.base import IngestionResult, SourceFeature
from app.services.data_ingestion.kml import iter_placemarks
from app.services.data_ingestion.persistence import DIM_POINT, upsert_rows
from app.services.data_ingestion.validation import (
    coerce_float,
    require_geometry,
    require_within_bbox,
)

logger = get_logger(__name__)

#: The GCC layer records depth in inches — confirmed by its KML schema name,
#: `chennai_flood_inundation_inches`. Normalised once, here, so nothing
#: downstream has to know the source unit.
INCHES_TO_CM = 2.54

#: Depths outside this band indicate a data error rather than a flood. The
#: observed range in the published file is 5–60 inches.
MIN_DEPTH_INCHES = 0.1
MAX_DEPTH_INCHES = 400.0

#: Depth thresholds used to map a measurement onto the severity enum. Chosen
#: from what the depth means for a road: below ~15 cm a car passes normally,
#: by ~30 cm most cars stall, and beyond ~60 cm a road is impassable and
#: dangerous. These are stated here rather than buried as magic numbers.
SEVERITY_MODERATE_CM = 15.0
SEVERITY_SEVERE_CM = 30.0


def severity_from_depth(depth_cm: float | None) -> IncidentSeverity:
    if depth_cm is None:
        return IncidentSeverity.UNKNOWN
    if depth_cm >= SEVERITY_SEVERE_CM:
        return IncidentSeverity.SEVERE
    if depth_cm >= SEVERITY_MODERATE_CM:
        return IncidentSeverity.MODERATE
    return IncidentSeverity.MINOR


class _FloodPointAdapter(CKANBackedSource):
    """Shared parsing and persistence for KML point flood layers."""

    category = "flood_history"
    record_type: FloodRecordType = FloodRecordType.EVENT_OBSERVATION

    @property
    def event_name(self) -> str | None:
        return self.config.get("event_name")

    @property
    def event_date(self) -> date | None:
        raw = self.config.get("event_date")
        return date.fromisoformat(raw) if raw else None

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        for index, placemark in enumerate(iter_placemarks(payload)):
            if placemark.error:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason=placemark.error
                )
                continue

            points = [wkt for kind, wkt in placemark.geometries if kind == "Point"]
            if not points:
                yield SourceFeature(
                    external_id=None, properties={}, rejection_reason="no_point_geometry"
                )
                continue

            properties = dict(placemark.properties)
            properties["name"] = placemark.name
            external_id = str(
                properties.get("F_ID") or properties.get("OBJECTID") or f"row-{index}"
            )

            yield SourceFeature(
                external_id=external_id,
                properties=properties,
                geometry_wkt=points[0],
                geometry_type="Point",
            )

    def rules(self, bbox: list[float]) -> list[Any]:
        return [require_geometry, lambda f: require_within_bbox(f, bbox, margin=0.5)]

    def _row(self, feature: SourceFeature, *, data_source_id: Any, city_id: Any) -> dict[str, Any]:
        raise NotImplementedError

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        rows = [self._row(f, data_source_id=data_source_id, city_id=city_id) for f in features]
        written = await upsert_rows(
            session,
            table="flood_incidents",
            columns=[
                "data_source_id",
                "city_id",
                "external_id",
                "record_type",
                "event_name",
                "occurred_on",
                "severity",
                "reported_depth_cm",
                "location_description",
                "geom",
            ],
            conflict_columns=["data_source_id", "external_id"],
            update_columns=[
                "record_type",
                "event_name",
                "occurred_on",
                "severity",
                "reported_depth_cm",
                "location_description",
            ],
            rows=rows,
            geometry_dimension=DIM_POINT,
        )
        result.records_written = written
        _account_for_unwritten(result, attempted=len(rows), written=written)


class InundationPointAdapter(_FloodPointAdapter):
    """Chennai inundation points with measured depth.

    Rejects a point whose depth is missing or implausible rather than storing
    it with a NULL depth: depth is the only quantitative signal this layer
    carries, and a depthless point silently weakens the training label.
    """

    record_type = FloodRecordType.INUNDATION_POINT

    def rules(self, bbox: list[float]) -> list[Any]:
        def depth_present(feature: SourceFeature) -> None:
            coerce_float(
                feature,
                "DEPTH",
                required=True,
                minimum=MIN_DEPTH_INCHES,
                maximum=MAX_DEPTH_INCHES,
            )

        return [*super().rules(bbox), depth_present]

    def _row(self, feature: SourceFeature, *, data_source_id: Any, city_id: Any) -> dict[str, Any]:
        depth_inches = float(feature.properties["DEPTH"])
        depth_cm = round(depth_inches * INCHES_TO_CM, 1)
        return {
            "data_source_id": data_source_id,
            "city_id": city_id,
            "external_id": feature.external_id,
            "record_type": self.record_type.name,
            "event_name": None,
            "occurred_on": None,
            "severity": severity_from_depth(depth_cm).name,
            "reported_depth_cm": depth_cm,
            "location_description": feature.properties.get("F_REMARKS"),
            "geom_wkt": feature.geometry_wkt,
        }


class FloodEventPointAdapter(_FloodPointAdapter):
    """Locations flooded during a named, dated event."""

    record_type = FloodRecordType.EVENT_OBSERVATION

    def _row(self, feature: SourceFeature, *, data_source_id: Any, city_id: Any) -> dict[str, Any]:
        return {
            "data_source_id": data_source_id,
            "city_id": city_id,
            "external_id": feature.external_id,
            "record_type": self.record_type.name,
            "event_name": self.event_name,
            "occurred_on": self.event_date,
            # The event layers record no depth, so severity stays UNKNOWN
            # rather than being inferred from the fact of being listed.
            "severity": IncidentSeverity.UNKNOWN.name,
            "reported_depth_cm": None,
            "location_description": feature.properties.get("name"),
            "geom_wkt": feature.geometry_wkt,
        }
