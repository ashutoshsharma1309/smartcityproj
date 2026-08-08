"""Time-series observations and historical incidents.

These are the model's training inputs and labels. They stay empty until the
Phase 2 ingestion jobs run against real providers.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.city import City
from app.models.geography import SRID, Zone
from app.models.provenance import DataSource


class WeatherObservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Hourly weather for one zone.

    Deliberately zone-keyed rather than station-keyed: providers such as
    Open-Meteo serve gridded reanalysis, so the natural unit is the zone
    centroid. Antecedent-rainfall features are computed from this table.
    """

    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint(
            "zone_id", "observed_at", "data_source_id", name="weather_zone_time_source"
        ),
        Index("ix_weather_observations_zone_time", "zone_id", "observed_at"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: True when the row is a forecast rather than a past measurement.
    is_forecast: Mapped[bool] = mapped_column(nullable=False, default=False)

    precipitation_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_pressure_hpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture_frac: Mapped[float | None] = mapped_column(Float, nullable=True)

    data_source: Mapped[DataSource] = relationship()
    zone: Mapped[Zone] = relationship()


class TideObservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tide height for coastal cities.

    Coastal waterlogging is strongly modulated by high tide blocking gravity
    drainage, so tide level is a first-class predictor rather than an add-on.
    """

    __tablename__ = "tide_observations"
    __table_args__ = (UniqueConstraint("station_code", "observed_at", name="tide_station_time"),)

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    station_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    height_m: Mapped[float] = mapped_column(Float, nullable=False)
    is_forecast: Mapped[bool] = mapped_column(nullable=False, default=False)

    data_source: Mapped[DataSource] = relationship()


class IncidentSeverity(enum.StrEnum):
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    UNKNOWN = "unknown"


class FloodRecordType(enum.StrEnum):
    """What kind of evidence a flood record represents.

    Kept explicit because the two kinds cannot be pooled: one says *where*
    flooding happens, the other says *where and when*.
    """

    INUNDATION_POINT = "inundation_point"
    """A location known to inundate, with depth but no date."""

    EVENT_OBSERVATION = "event_observation"
    """A location flooded during a named, dated event."""


class FloodIncident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A recorded flooding or waterlogging observation — the supervised label.

    Two kinds of record share this table, distinguished by ``record_type``:

    * ``inundation_point`` — a location known to inundate, with a measured
      depth but **no date**. This is a spatial susceptibility label.
    * ``event_observation`` — a location flooded during a named, dated event
      (the 2015 Chennai floods, Cyclone Nivar in 2020).

    ``occurred_on`` is therefore nullable, which is a deliberate schema
    decision: the largest and most detailed Chennai flood layer carries no
    timestamp at all, and forcing a date would mean inventing one. Phase 3 must
    read ``record_type`` and treat the two kinds differently rather than
    pooling them into a single time series.
    """

    __tablename__ = "flood_incidents"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="incident_external_id"),
        Index("ix_flood_incidents_geom", "geom", postgresql_using="gist"),
        Index("ix_flood_incidents_occurred", "occurred_on"),
        Index("ix_flood_incidents_city_type", "city_id", "record_type"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    record_type: Mapped[FloodRecordType] = mapped_column(
        Enum(FloodRecordType, name="flood_record_type", native_enum=True),
        nullable=False,
        default=FloodRecordType.EVENT_OBSERVATION,
    )
    #: Name of the flood event, where the source attributes one.
    event_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: NULL for undated susceptibility points — see the class docstring.
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity", native_enum=True),
        nullable=False,
        default=IncidentSeverity.UNKNOWN,
    )
    #: Normalised to centimetres. The GCC source publishes inches — the
    #: conversion happens once, at ingest, so no consumer has to know.
    reported_depth_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID, spatial_index=False), nullable=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()
    zone: Mapped[Zone | None] = relationship()
