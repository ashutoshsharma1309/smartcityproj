"""Geospatial entities: analysis zones and road segments.

All geometries are stored in EPSG:4326 (WGS84) because that is what both the
upstream sources (OSM, administrative boundary files) and MapLibre expect.
Area and length computations must therefore be done in a projected CRS via
``ST_Transform`` or ``geography`` casts — never on raw degrees.
"""

from __future__ import annotations

import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.city import City
from app.models.provenance import DataSource

SRID = 4326


class Zone(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A polygonal unit of analysis.

    Holds both administrative wards (``zone_type='ward'``) and hydrological
    microwatersheds (``zone_type='watershed'``). They share this table because
    they serve the same downstream purpose — a polygon that risk is computed
    over — and separating them would mean duplicating every spatial query.

    The distinction matters analytically, though: water obeys catchments, not
    ward lines. Predictions are computed on watersheds and reported on wards,
    which is the boundary a municipal user acts on.

    Terrain attributes are populated by the offline geospatial pipeline and are
    nullable until it has run.
    """

    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="zone_external_id"),
        Index("ix_zones_geom", "geom", postgresql_using="gist"),
        Index("ix_zones_city_type", "city_id", "zone_type"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False
    )
    #: Identifier used by the upstream authority (e.g. ward code).
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: "ward" | "watershed" | "grid_cell" | "district".
    zone_type: Mapped[str] = mapped_column(String(60), nullable=False)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID, spatial_index=False), nullable=False
    )

    # -- terrain attributes derived by the offline geospatial pipeline --------
    area_sq_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_slope_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Fraction of the zone covered by impervious surfaces, 0.0-1.0.
    impervious_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Metres to the nearest mapped watercourse or drain.
    distance_to_water_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()
    road_segments: Mapped[list[RoadSegment]] = relationship(back_populates="zone")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Zone {self.zone_type}:{self.external_id} {self.name}>"


class RoadSegment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A stretch of road.

    Fed by two sources with complementary strengths: the Greater Chennai
    Corporation centreline layer is authoritative on geometry and street names
    but carries no classification, while OpenStreetMap supplies ``highway``
    class, lanes, speed limits and bridge/tunnel flags. Both land here,
    distinguished by ``data_source_id``.

    Impact analysis intersects flooded zones with these segments and uses
    ``NetworkX`` over the segment graph to find severed routes.
    """

    __tablename__ = "road_segments"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="road_external_id"),
        Index("ix_road_segments_geom", "geom", postgresql_using="gist"),
        Index("ix_road_segments_city_class", "city_id", "highway_class"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False
    )
    #: Publisher's identifier — an OSM way id, or a GCC ``road_id``.
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: OSM ``highway`` tag value, or "unclassified" when the source omits it.
    highway_class: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    lanes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_limit_kph: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_bridge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_tunnel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_oneway: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Recomputed in PostGIS on a projected CRS — publisher lengths state no units.
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=SRID, spatial_index=False), nullable=False
    )
    #: Zone the segment's centroid falls in; resolved by the geospatial pipeline.
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Remaining source tags, retained so features can be re-derived without refetching.
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()
    zone: Mapped[Zone | None] = relationship(back_populates="road_segments")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RoadSegment {self.external_id} class={self.highway_class}>"


class DrainageAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Storm water drains, as published by the municipal corporation.

    ``capacity_cumecs`` stays NULL: the GCC SWD map publishes geometry only,
    with no cross-section or design capacity. Only drain density and
    distance-to-drain can be derived, and capacity is not guessed.
    """

    __tablename__ = "drainage_assets"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="drainage_external_id"),
        Index("ix_drainage_assets_geom", "geom", postgresql_using="gist"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: e.g. "storm_drain", "pumping_station", "nallah", "culvert".
    asset_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capacity_cumecs: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=SRID, spatial_index=False), nullable=False
    )

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()
