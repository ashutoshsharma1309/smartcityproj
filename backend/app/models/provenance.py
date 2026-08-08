"""Data provenance models.

Every observational row in UrbanPulse points at a :class:`DataSource`. This is
a deliberate schema-level guarantee: it is impossible to store a measurement
without recording where it came from and whether it is real or simulated.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DataOrigin(enum.StrEnum):
    """Where a dataset's values actually come from.

    ``SIMULATED`` exists so the simulation layer can be surfaced in the UI and
    the API without ever being mistaken for observed data.
    """

    OBSERVED = "observed"
    """Measured or recorded by an external authority (weather station, survey)."""

    DERIVED = "derived"
    """Computed by UrbanPulse from observed inputs (e.g. slope from a DEM)."""

    SIMULATED = "simulated"
    """Produced by the UrbanPulse simulation layer. Never real-world truth."""


class DataSourceKind(enum.StrEnum):
    """Category of a registered dataset.

    Values mirror the ``category`` field in ``data/metadata/catalog.json``, so
    the catalogue and the database speak the same vocabulary.
    """

    WEATHER = "weather"
    ELEVATION = "elevation"
    ROAD_NETWORK = "road_network"
    ADMINISTRATIVE_BOUNDARY = "administrative_boundary"
    DRAINAGE = "drainage"
    LAND_COVER = "land_cover"
    HISTORICAL_INCIDENT = "historical_incident"
    TRAFFIC = "traffic"
    HYDROLOGY = "hydrology"
    CIVIC = "civic"


class DataSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A registered upstream dataset or API.

    Rows are created by ``scripts/register_data_sources.py`` from the manifest
    in ``data/metadata/``, not by hand.
    """

    __tablename__ = "data_sources"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[DataSourceKind] = mapped_column(
        Enum(DataSourceKind, name="data_source_kind", native_enum=True), nullable=False
    )
    origin: Mapped[DataOrigin] = mapped_column(
        Enum(DataOrigin, name="data_origin", native_enum=True), nullable=False
    )
    #: Canonical URL of the dataset or API documentation.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    #: SPDX-style identifier or the licence name as published by the provider.
    license: Mapped[str] = mapped_column(String(255), nullable=False)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: How often the upstream data changes, in seconds. NULL for static datasets.
    update_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    ingestion_runs: Mapped[list[IngestionRun]] = relationship(
        back_populates="data_source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DataSource {self.slug} origin={self.origin.value}>"


class IngestionStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class IngestionRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit record for one execution of an ingestion job.

    This row *is* the validation report. Data quality is computed from these
    columns rather than from a separately maintained score, so a quality figure
    can never drift from the run that produced it.

    The source checksum makes a run reproducible: the same bytes are provably
    the same input.
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (UniqueConstraint("data_source_id", "started_at", name="run_per_source"),)

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="ingestion_status", native_enum=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Features read from the source, before any validation.
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Rejection reason -> count. Summing the values gives ``records_rejected``,
    #: so no record can be discarded without appearing here.
    rejection_reasons: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Where the bytes came from and what they hashed to.
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Free-form provider request parameters, kept for reproducibility.
    request_parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    data_source: Mapped[DataSource] = relationship(back_populates="ingestion_runs")
