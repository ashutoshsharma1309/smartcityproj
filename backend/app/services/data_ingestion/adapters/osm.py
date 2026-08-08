"""OpenStreetMap road network via the Overpass API.

Ingested alongside the GCC centreline layer because the two are complementary:
GCC is authoritative on geometry and street naming, OSM supplies the road
classification, lane counts, speed limits and bridge/tunnel flags that impact
analysis needs and that GCC does not publish.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.data_ingestion.adapters.vector import _account_for_unwritten
from app.services.data_ingestion.base import BaseDataSource, IngestionResult, SourceFeature
from app.services.data_ingestion.geometry import GeometryError, linestring_wkt, validate_lonlat
from app.services.data_ingestion.persistence import DIM_LINE, upsert_rows
from app.services.data_ingestion.validation import (
    coerce_int,
    require_geometry,
    require_within_bbox,
)

logger = get_logger(__name__)

#: Road classes that carry motor traffic. Footpaths and cycleways are excluded:
#: they neither carry the traffic that flooding disrupts nor belong in the
#: vehicle routing graph used for impact analysis.
HIGHWAY_CLASSES = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
)

MAX_PLAUSIBLE_LANES = 24
MAX_PLAUSIBLE_SPEED_KPH = 200


def build_query(bbox: list[float], *, timeout_seconds: int = 180) -> str:
    """Overpass QL for drivable ways in a bounding box.

    ``out geom`` returns coordinates inline, avoiding a second pass to resolve
    node references.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    classes = "|".join(HIGHWAY_CLASSES)
    return f"""
[out:json][timeout:{timeout_seconds}];
way["highway"~"^({classes})$"]({min_lat},{min_lon},{max_lat},{max_lon});
out geom;
""".strip()


def parse_maxspeed(value: str | None) -> int | None:
    """Parse an OSM ``maxspeed`` tag into km/h.

    OSM stores bare numbers as km/h and marks other units explicitly, most
    commonly ``"30 mph"``. Anything non-numeric (``"IN:urban"``) yields None
    rather than a guess.
    """
    if not value:
        return None
    text = value.strip().lower()
    multiplier = 1.0
    if "mph" in text:
        multiplier = 1.60934
        text = text.replace("mph", "").strip()
    elif "knots" in text:
        return None
    try:
        speed = int(round(float(text.split()[0]) * multiplier))
    except (ValueError, IndexError):
        return None
    if not (0 < speed <= MAX_PLAUSIBLE_SPEED_KPH):
        return None
    return speed


class OverpassRoadAdapter(BaseDataSource):
    category = "road_network"

    async def resolve_url(self) -> str:
        return str(self.config["access"]["base_url"])

    def cache_filename(self) -> str:
        return f"{self.dataset_id}.json"

    async def fetch(self, *, force: bool = False):  # type: ignore[override]
        """Overpass needs a POST body, so the base GET fetch is overridden."""
        import hashlib
        from datetime import UTC, datetime

        import httpx

        from app.services.data_ingestion.base import FetchResult

        target = self.raw_dir / self.cache_filename()
        url = await self.resolve_url()

        if target.exists() and not force:
            payload = target.read_bytes()
            logger.info("fetch_cache_hit", dataset=self.dataset_id, path=str(target))
            return FetchResult(
                path=target,
                bytes_downloaded=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                from_cache=True,
                source_url=url,
                fetched_at=datetime.now(UTC),
            )

        query = build_query(self.config["bbox"])
        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("overpass_query_start", dataset=self.dataset_id)

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers={"User-Agent": "UrbanPulse/0.2 (urban flood risk research)"},
        ) as client:
            response = await client.post(url, data={"data": query})
            response.raise_for_status()
            payload = response.content

        target.write_bytes(payload)
        return FetchResult(
            path=target,
            bytes_downloaded=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            from_cache=False,
            source_url=url,
            fetched_at=datetime.now(UTC),
        )

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        document = json.loads(payload.decode("utf-8"))
        for element in document.get("elements", []):
            if element.get("type") != "way":
                continue

            geometry = element.get("geometry") or []
            tags = element.get("tags") or {}
            try:
                coordinates = [
                    validate_lonlat(float(node["lon"]), float(node["lat"])) for node in geometry
                ]
                wkt = linestring_wkt(coordinates)
            except (GeometryError, KeyError, TypeError, ValueError) as exc:
                yield SourceFeature(
                    external_id=str(element.get("id")),
                    properties={},
                    rejection_reason=f"invalid_geometry:{exc}",
                )
                continue

            yield SourceFeature(
                external_id=str(element["id"]),
                properties={"tags": tags},
                geometry_wkt=wkt,
                geometry_type="LineString",
            )

    def rules(self, bbox: list[float]) -> list[Any]:
        return [require_geometry, lambda f: require_within_bbox(f, bbox, margin=0.3)]

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        rows = []
        for feature in features:
            tags: dict[str, Any] = feature.properties.get("tags", {})
            lanes_feature = SourceFeature(external_id=None, properties=tags)
            rows.append(
                {
                    "data_source_id": data_source_id,
                    "city_id": city_id,
                    "external_id": feature.external_id,
                    "name": tags.get("name"),
                    "highway_class": tags.get("highway", "unclassified"),
                    "lanes": coerce_int(lanes_feature, "lanes", maximum=MAX_PLAUSIBLE_LANES),
                    "speed_limit_kph": parse_maxspeed(tags.get("maxspeed")),
                    "is_bridge": tags.get("bridge") not in (None, "no"),
                    "is_tunnel": tags.get("tunnel") not in (None, "no"),
                    "is_oneway": tags.get("oneway") in ("yes", "true", "1", "-1"),
                    "tags": json.dumps(tags),
                    "geom_wkt": feature.geometry_wkt,
                }
            )

        written = await upsert_rows(
            session,
            table="road_segments",
            columns=[
                "data_source_id",
                "city_id",
                "external_id",
                "name",
                "highway_class",
                "lanes",
                "speed_limit_kph",
                "is_bridge",
                "is_tunnel",
                "is_oneway",
                "tags",
                "geom",
            ],
            conflict_columns=["data_source_id", "external_id"],
            update_columns=[
                "name",
                "highway_class",
                "lanes",
                "speed_limit_kph",
                "is_bridge",
                "is_tunnel",
                "is_oneway",
                "tags",
            ],
            rows=rows,
            geometry_dimension=DIM_LINE,
        )
        result.records_written = written
        _account_for_unwritten(result, attempted=len(rows), written=written)
