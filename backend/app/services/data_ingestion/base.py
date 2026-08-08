"""Ingestion framework core.

Every dataset enters UrbanPulse through the same five stages:

    fetch -> parse -> validate -> normalise -> persist

``BaseDataSource`` owns that sequence; an adapter supplies only the parts that
differ per dataset. Adding a source therefore means implementing ``parse`` and
``normalise`` — never re-implementing caching, validation accounting or the
provenance write, which is what keeps the guarantees uniform.

Two rules hold for every adapter:

* A record that fails validation is *counted and reported*, never silently
  dropped. ``IngestionResult`` carries the reason breakdown.
* Nothing is written without a ``data_source_id``. The schema enforces it; this
  framework makes it automatic.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Interchange CRS for everything in the platform.
SRID = 4326


@dataclass(slots=True)
class SourceFeature:
    """One feature as read from upstream, before any validation.

    ``geometry_wkt`` is Well-Known Text in EPSG:4326. WKT is used as the
    handoff format because PostGIS parses and validates it natively, so the
    ingestion process needs no GEOS bindings of its own.
    """

    external_id: str | None
    properties: dict[str, Any]
    geometry_wkt: str | None = None
    geometry_type: str | None = None
    #: Set by the validation stage; ``None`` means the feature passed.
    rejection_reason: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.rejection_reason is None


@dataclass(slots=True)
class FetchResult:
    """Bytes retrieved from upstream, plus what is needed to reproduce it."""

    path: Path
    bytes_downloaded: int
    sha256: str
    from_cache: bool
    source_url: str
    fetched_at: datetime


@dataclass(slots=True)
class IngestionResult:
    """Outcome of one ingestion run. Mirrors the `ingestion_runs` table."""

    dataset_id: str
    started_at: datetime
    finished_at: datetime | None = None
    records_received: int = 0
    records_valid: int = 0
    records_written: int = 0
    records_rejected: int = 0
    duplicates: int = 0
    #: Rejection reason -> count. The sum equals ``records_rejected``.
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    source_url: str | None = None
    source_sha256: str | None = None
    from_cache: bool = False
    error: str | None = None

    def reject(self, reason: str, count: int = 1) -> None:
        self.records_rejected += count
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + count

    def as_report(self) -> dict[str, Any]:
        """The validation report described in the Phase 2 brief."""
        return {
            "dataset": self.dataset_id,
            "records_received": self.records_received,
            "valid_records": self.records_valid,
            "invalid_records": self.records_rejected,
            "records_written": self.records_written,
            "duplicates": self.duplicates,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
            "source_url": self.source_url,
            "source_sha256": self.source_sha256,
            "from_cache": self.from_cache,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


class BaseDataSource(ABC):
    """Template for every dataset adapter.

    Subclasses implement :meth:`parse` and :meth:`persist`; everything else —
    caching, hashing, validation accounting, reporting — is inherited.
    """

    #: Catalogue id this adapter serves. Set by the registry when instantiated.
    dataset_id: str
    #: Human-readable category, used for reporting.
    category: str

    def __init__(
        self,
        dataset_id: str,
        *,
        raw_dir: Path,
        config: dict[str, Any],
        timeout_seconds: float = 120.0,
    ) -> None:
        self.dataset_id = dataset_id
        self.config = config
        self.raw_dir = raw_dir
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------- fetching
    async def fetch(self, *, force: bool = False) -> FetchResult:
        """Download the source payload, caching it under ``data/raw``.

        Caching is not an optimisation detail — it is what makes a run
        reproducible and keeps repeated development runs from hammering a free
        public API.
        """
        url = await self.resolve_url()
        target = self.raw_dir / self.cache_filename()

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

        target.parent.mkdir(parents=True, exist_ok=True)
        logger.info("fetch_start", dataset=self.dataset_id, url=url)

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "UrbanPulse/0.2 (urban flood risk research)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.content

        target.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        logger.info(
            "fetch_complete",
            dataset=self.dataset_id,
            bytes=len(payload),
            sha256=digest[:16],
        )
        return FetchResult(
            path=target,
            bytes_downloaded=len(payload),
            sha256=digest,
            from_cache=False,
            source_url=url,
            fetched_at=datetime.now(UTC),
        )

    async def resolve_url(self) -> str:
        """Where to download from. Overridden by adapters that resolve indirectly."""
        url = self.config.get("access", {}).get("base_url") or self.config.get("url")
        if not url:
            raise ValueError(f"{self.dataset_id}: no URL configured")
        return str(url)

    def cache_filename(self) -> str:
        fmt = (self.config.get("format") or "bin").lower()
        suffix = {"geojson": "geojson", "kml": "kml", "json": "json"}.get(fmt, "bin")
        return f"{self.dataset_id}.{suffix}"

    # -------------------------------------------------------------- parsing
    @abstractmethod
    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        """Turn raw bytes into features. No validation, no normalisation."""

    # ------------------------------------------------------------ persisting
    @abstractmethod
    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
    ) -> None:
        """Write validated features. Must update ``result.records_written``."""

    # -------------------------------------------------------------- staging
    def write_staging(self, features: list[SourceFeature], staging_dir: Path) -> Path:
        """Persist normalised features as NDJSON before they reach the database.

        Keeping this intermediate artefact means a persistence failure can be
        debugged, and re-run, without re-fetching from the provider.
        """
        staging_dir.mkdir(parents=True, exist_ok=True)
        path = staging_dir / f"{self.dataset_id}.ndjson"
        with path.open("w", encoding="utf-8") as handle:
            for feature in features:
                handle.write(
                    json.dumps(
                        {
                            "external_id": feature.external_id,
                            "properties": feature.properties,
                            "geometry_type": feature.geometry_type,
                            "geometry_wkt": feature.geometry_wkt,
                        },
                        default=str,
                    )
                    + "\n"
                )
        return path
