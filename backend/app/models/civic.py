"""Civic complaint / grievance records.

The table and its adapter exist but hold no data: no Chennai grievance system
publishes a documented open API, and data.gov.in requires a registered key that
cannot be provisioned non-interactively. See ``unavailable`` in
``data/metadata/catalog.json``.

The schema is defined now so that plugging in a feed later is an adapter, not a
migration.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.city import City
from app.models.geography import SRID, Zone
from app.models.provenance import DataSource


class ComplaintStatus(enum.StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class CivicIncident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "civic_incidents"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="civic_external_id"),
        Index("ix_civic_incidents_geom", "geom", postgresql_using="gist"),
        Index("ix_civic_incidents_reported", "reported_at"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Publisher's own category string, kept verbatim rather than mapped to an
    #: internal taxonomy that would lose information.
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus, name="complaint_status", native_enum=True),
        nullable=False,
        default=ComplaintStatus.UNKNOWN,
    )
    geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID, spatial_index=False), nullable=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()
    zone: Mapped[Zone | None] = relationship()
