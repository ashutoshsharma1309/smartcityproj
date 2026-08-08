"""Service contracts for the UrbanPulse intelligence pipeline.

The pipeline is strictly ordered and each stage is a separate protocol:

    ingestion -> validation -> geospatial -> features -> risk
             -> impact -> recommendations -> LLM explanation

Two rules are encoded here rather than left to convention:

1. The LLM sits at the *end* of the chain and consumes only structured objects
   produced by earlier stages. :class:`ExplanationService` cannot be handed raw
   user text or asked for a number — its input type is
   :class:`~app.schemas.risk.ExplanationRequest`.
2. Any stage that cannot answer from real data raises
   :class:`~app.core.exceptions.DataUnavailableError` instead of returning a
   fabricated result.

Protocols are used rather than ABCs so implementations can live in other
packages (or be swapped for fakes in tests) without inheriting from this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.schemas.catalog import IngestionRunRead
from app.schemas.common import GeoJSONFeatureCollection
from app.schemas.risk import (
    ExplanationRequest,
    ExplanationResponse,
    ImpactAssessment,
    RecommendedAction,
    RiskSurface,
    ZoneRiskPrediction,
)


@runtime_checkable
class IngestionService(Protocol):
    """Pulls data from an external provider into the warehouse.

    Implementations must write an :class:`~app.models.provenance.IngestionRun`
    row for every attempt, successful or not.
    """

    async def ingest(
        self,
        source_slug: str,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> IngestionRunRead:
        """Fetch and persist records for one registered data source."""
        ...

    async def available_sources(self) -> list[str]:
        """Slugs this service knows how to fetch."""
        ...


@runtime_checkable
class ValidationService(Protocol):
    """Rejects records that fail schema, range or topology checks.

    Kept separate from ingestion so validation rules can be unit-tested and
    reused by the offline training pipeline.
    """

    async def validate_run(self, run_id: UUID) -> dict[str, int]:
        """Return counts keyed by rejection reason for one ingestion run."""
        ...


@runtime_checkable
class GeospatialService(Protocol):
    """Builds and queries the city's geometric representation."""

    async def zones(
        self, *, bbox: tuple[float, float, float, float] | None = None
    ) -> GeoJSONFeatureCollection: ...

    async def road_network(
        self, *, bbox: tuple[float, float, float, float] | None = None
    ) -> GeoJSONFeatureCollection: ...

    async def derive_terrain_attributes(self, zone_id: UUID) -> None:
        """Compute elevation, slope and imperviousness for a zone from a DEM."""
        ...


@runtime_checkable
class FeatureService(Protocol):
    """Turns stored observations into the model's feature matrix.

    The same code path serves training and inference so the two cannot drift.
    """

    async def build_features(
        self, *, zone_ids: list[UUID], as_of: datetime
    ) -> dict[UUID, dict[str, float | None]]:
        """Feature vector per zone. ``None`` marks a genuinely missing input."""
        ...


@runtime_checkable
class PredictionService(Protocol):
    """Numerical flood-risk prediction. Never delegated to an LLM."""

    async def predict_zone(self, zone_id: UUID, *, as_of: datetime) -> ZoneRiskPrediction: ...

    async def predict_city(self, *, as_of: datetime) -> RiskSurface: ...

    @property
    def model_version(self) -> str:
        """Identifier of the loaded model artefact."""
        ...


@runtime_checkable
class ImpactService(Protocol):
    """Translates zone risk into consequences for roads and access."""

    async def assess(
        self, surface: RiskSurface, *, risk_threshold: float = 0.5
    ) -> ImpactAssessment: ...


@runtime_checkable
class RecommendationService(Protocol):
    """Deterministic rules engine mapping risk and impact to municipal actions.

    Rule-based rather than generative so every recommendation is auditable and
    reproducible.
    """

    async def recommend(
        self, surface: RiskSurface, impact: ImpactAssessment
    ) -> list[RecommendedAction]: ...


@runtime_checkable
class ExplanationService(Protocol):
    """Renders already-computed facts as natural language.

    The only stage permitted to call an external LLM. It must not invent
    values, and must raise rather than guess when a fact is missing.
    """

    async def explain(self, request: ExplanationRequest) -> ExplanationResponse: ...

    @property
    def provider_name(self) -> str: ...


@runtime_checkable
class AlertService(Protocol):
    """Emits events when risk crosses configured thresholds."""

    async def evaluate(self, surface: RiskSurface) -> list[str]:
        """Return ids of alerts raised for this forecast run."""
        ...
