"""Ingestion orchestration.

Runs one catalogued dataset through the pipeline and records the outcome as an
``ingestion_runs`` row — successes and failures alike. A run that crashes still
leaves an audit record explaining why, which is what makes the data-quality
figures trustworthy rather than optimistic.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.provenance import IngestionStatus
from app.services.data_ingestion.adapters import get_adapter_class
from app.services.data_ingestion.adapters.weather import (
    OpenMeteoArchiveAdapter,
    OpenMeteoElevationAdapter,
    OpenMeteoForecastAdapter,
)
from app.services.data_ingestion.base import BaseDataSource, IngestionResult
from app.services.data_ingestion.catalog import Catalog, DatasetEntry, get_catalog, repo_root
from app.services.data_ingestion.validation import run_rules

logger = get_logger(__name__)


def data_dir() -> Path:
    return repo_root() / "data"


class DatasetNotRegisteredError(RuntimeError):
    """The catalogue entry has no matching ``data_sources`` row.

    Ingestion refuses to proceed: writing records without provenance is exactly
    what the schema is designed to prevent.
    """


async def _resolve_ids(
    session: AsyncSession, *, dataset_id: str, city_slug: str
) -> tuple[UUID, UUID, list[float]]:
    source = (
        await session.execute(
            text("SELECT id FROM data_sources WHERE slug = :slug"), {"slug": dataset_id}
        )
    ).first()
    if source is None:
        raise DatasetNotRegisteredError(
            f"Dataset '{dataset_id}' is not registered. "
            "Run `python -m scripts.seed.catalog` first."
        )

    city = (
        await session.execute(
            text(
                "SELECT id, min_lon, min_lat, max_lon, max_lat "
                "FROM cities WHERE slug = :slug"
            ),
            {"slug": city_slug},
        )
    ).first()
    if city is None:
        raise DatasetNotRegisteredError(
            f"City '{city_slug}' is not registered. Run `python -m scripts.seed.city` first."
        )

    bbox = [float(city.min_lon), float(city.min_lat), float(city.max_lon), float(city.max_lat)]
    return source.id, city.id, bbox


async def _record_run(
    session: AsyncSession,
    *,
    data_source_id: UUID,
    result: IngestionResult,
    status: IngestionStatus,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ingestion_runs (
                id, data_source_id, status, started_at, finished_at,
                records_received, records_valid, records_written, records_rejected,
                duplicates, rejection_reasons, source_url, source_sha256,
                error_message, created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :data_source_id, :status, :started_at, :finished_at,
                :records_received, :records_valid, :records_written, :records_rejected,
                :duplicates, CAST(:rejection_reasons AS jsonb), :source_url, :source_sha256,
                :error_message, now(), now()
            )
            ON CONFLICT (data_source_id, started_at) DO NOTHING
            """
        ),
        {
            "data_source_id": data_source_id,
            "status": status.name,
            "started_at": result.started_at,
            "finished_at": result.finished_at or datetime.now(UTC),
            "records_received": result.records_received,
            "records_valid": result.records_valid,
            "records_written": result.records_written,
            "records_rejected": result.records_rejected,
            "duplicates": result.duplicates,
            "rejection_reasons": json.dumps(result.rejection_reasons),
            "source_url": result.source_url,
            "source_sha256": result.source_sha256,
            "error_message": result.error,
        },
    )


def build_adapter(entry: DatasetEntry, *, bbox: list[float] | None = None) -> BaseDataSource:
    adapter_class = get_adapter_class(entry.adapter)
    config = entry.model_dump()
    if bbox is not None:
        config["bbox"] = bbox
    return adapter_class(
        entry.id,
        raw_dir=data_dir() / "raw",
        config=config,
    )


async def ingest_dataset(
    session: AsyncSession,
    dataset_id: str,
    *,
    city_slug: str,
    catalog: Catalog | None = None,
    force_download: bool = False,
    weather_start: date | None = None,
    weather_end: date | None = None,
    elevation_grid_size: int = 20,
    max_zones: int | None = None,
) -> IngestionResult:
    """Run one dataset through fetch -> parse -> validate -> persist."""
    catalog = catalog or get_catalog()
    entry = catalog.by_id(dataset_id)

    result = IngestionResult(dataset_id=dataset_id, started_at=datetime.now(UTC))
    data_source_id, city_id, bbox = await _resolve_ids(
        session, dataset_id=dataset_id, city_slug=city_slug
    )
    adapter = build_adapter(entry, bbox=bbox)

    try:
        # Open-Meteo adapters query per zone rather than downloading one file,
        # so they own their fetch loop.
        if isinstance(adapter, OpenMeteoElevationAdapter):
            await adapter.ingest_grid(
                session,
                data_source_id=data_source_id,
                city_id=city_id,
                bbox=bbox,
                grid_size=elevation_grid_size,
                result=result,
            )
        elif isinstance(adapter, OpenMeteoForecastAdapter):
            await adapter.ingest_weather(
                session,
                data_source_id=data_source_id,
                city_id=city_id,
                result=result,
                max_zones=max_zones,
            )
        elif isinstance(adapter, OpenMeteoArchiveAdapter):
            if weather_start is None or weather_end is None:
                raise ValueError("weather_start and weather_end are required for archive ingestion")
            await adapter.ingest_weather(
                session,
                data_source_id=data_source_id,
                city_id=city_id,
                start_date=weather_start,
                end_date=weather_end,
                result=result,
                max_zones=max_zones,
            )
        else:
            fetched = await adapter.fetch(force=force_download)
            result.source_url = fetched.source_url
            result.source_sha256 = fetched.sha256
            result.from_cache = fetched.from_cache

            payload = fetched.path.read_bytes()
            rules = adapter.rules(bbox) if hasattr(adapter, "rules") else []
            valid = list(
                run_rules(
                    adapter.parse(payload),
                    rules,
                    result,
                    duplicate_key=lambda f: f.external_id,
                )
            )
            adapter.write_staging(valid, data_dir() / "staging")
            await adapter.persist(
                session,
                valid,
                data_source_id=data_source_id,
                city_id=city_id,
                result=result,
            )

        result.finished_at = datetime.now(UTC)
        status = IngestionStatus.SUCCEEDED if result.error is None else IngestionStatus.FAILED
        await _record_run(session, data_source_id=data_source_id, result=result, status=status)
        await session.commit()

        logger.info(
            "ingestion_complete",
            dataset=dataset_id,
            received=result.records_received,
            valid=result.records_valid,
            written=result.records_written,
            rejected=result.records_rejected,
        )
        return result

    except Exception as exc:
        await session.rollback()
        result.finished_at = datetime.now(UTC)
        result.error = f"{type(exc).__name__}: {exc}"
        # The failure is recorded in its own transaction so the audit trail
        # survives whatever rolled the data back.
        await _record_run(
            session,
            data_source_id=data_source_id,
            result=result,
            status=IngestionStatus.FAILED,
        )
        await session.commit()
        logger.error("ingestion_failed", dataset=dataset_id, error=result.error)
        raise


def write_report(result: IngestionResult, *, processed_dir: Path | None = None) -> Path:
    """Write the validation report next to the processed data."""
    target_dir = processed_dir or (data_dir() / "processed")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{result.dataset_id}.validation.json"
    path.write_text(json.dumps(result.as_report(), indent=2), encoding="utf-8")
    return path


def load_reports(processed_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    target_dir = processed_dir or (data_dir() / "processed")
    reports: dict[str, dict[str, Any]] = {}
    if not target_dir.exists():
        return reports
    for path in sorted(target_dir.glob("*.validation.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        reports[report.get("dataset", path.stem)] = report
    return reports
