"""Data catalogue schemas — the public view of dataset provenance."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.provenance import DataOrigin, DataSourceKind, IngestionStatus
from app.schemas.common import APIModel


class DataSourceRead(APIModel):
    id: UUID
    slug: str
    name: str
    provider: str
    kind: DataSourceKind
    origin: DataOrigin = Field(
        description="observed | derived | simulated. Clients must surface 'simulated' to users."
    )
    source_url: str
    license: str
    attribution: str | None = None
    description: str | None = None
    update_interval_seconds: int | None = None
    is_active: bool


class IngestionRunRead(APIModel):
    id: UUID
    data_source_id: UUID
    status: IngestionStatus
    started_at: datetime
    finished_at: datetime | None
    records_written: int
    records_rejected: int
    error_message: str | None


class CatalogSummary(APIModel):
    """Row counts per table, so the UI can state exactly what data exists."""

    data_sources: int
    zones: int
    road_segments: int
    drainage_assets: int
    weather_observations: int
    tide_observations: int
    flood_incidents: int
