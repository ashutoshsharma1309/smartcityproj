"""Data access for the provenance catalogue."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.geography import DrainageAsset, RoadSegment, Zone
from app.models.observations import FloodIncident, TideObservation, WeatherObservation
from app.models.provenance import DataSource, DataSourceKind, IngestionRun
from app.schemas.catalog import CatalogSummary


class CatalogRepository:
    """Reads registered datasets and row counts.

    Counts are exact rather than estimated: the tables are small in Phase 1 and
    the UI uses them to state precisely what has been ingested.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_data_sources(
        self, *, kind: DataSourceKind | None = None, active_only: bool = False
    ) -> list[DataSource]:
        stmt = select(DataSource).order_by(DataSource.kind, DataSource.slug)
        if kind is not None:
            stmt = stmt.where(DataSource.kind == kind)
        if active_only:
            stmt = stmt.where(DataSource.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_data_source_by_slug(self, slug: str) -> DataSource | None:
        result = await self._session.execute(select(DataSource).where(DataSource.slug == slug))
        return result.scalar_one_or_none()

    async def list_ingestion_runs(self, *, limit: int = 50) -> list[IngestionRun]:
        stmt = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def summary(self) -> CatalogSummary:
        """One round trip returning every table count."""
        stmt = select(
            select(func.count()).select_from(DataSource).scalar_subquery(),
            select(func.count()).select_from(Zone).scalar_subquery(),
            select(func.count()).select_from(RoadSegment).scalar_subquery(),
            select(func.count()).select_from(DrainageAsset).scalar_subquery(),
            select(func.count()).select_from(WeatherObservation).scalar_subquery(),
            select(func.count()).select_from(TideObservation).scalar_subquery(),
            select(func.count()).select_from(FloodIncident).scalar_subquery(),
        )
        row = (await self._session.execute(stmt)).one()
        return CatalogSummary(
            data_sources=row[0],
            zones=row[1],
            road_segments=row[2],
            drainage_assets=row[3],
            weather_observations=row[4],
            tide_observations=row[5],
            flood_incidents=row[6],
        )
