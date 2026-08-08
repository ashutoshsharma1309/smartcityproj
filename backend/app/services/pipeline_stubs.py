"""Declared-but-unimplemented pipeline stages.

Each class satisfies its protocol from :mod:`app.services.interfaces` and
raises :class:`~app.core.exceptions.NotImplementedFeatureError`, which the API
returns as HTTP 501 with the owning module and the roadmap phase attached.

This is deliberate. The alternative — returning zeros, random numbers or
hardcoded sample predictions — would make the dashboard look finished while
being wrong, which is exactly the failure mode this project is built to avoid.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.core.exceptions import NotImplementedFeatureError
from app.schemas.catalog import IngestionRunRead
from app.schemas.risk import (
    ImpactAssessment,
    RecommendedAction,
    RiskSurface,
    ZoneRiskPrediction,
)


def _unimplemented(module: str, phase: str, capability: str) -> NotImplementedFeatureError:
    return NotImplementedFeatureError(
        f"{capability} is defined as an interface but has no implementation yet.",
        module=module,
        planned_phase=phase,
    )


class UnimplementedIngestionService:
    """Satisfies ``IngestionService``; ships in Phase 2."""

    async def ingest(
        self,
        source_slug: str,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> IngestionRunRead:
        raise _unimplemented("data_ingestion", "Phase 2", f"Ingestion of '{source_slug}'")

    async def available_sources(self) -> list[str]:
        return []


class UnimplementedValidationService:
    """Satisfies ``ValidationService``; ships in Phase 2."""

    async def validate_run(self, run_id: UUID) -> dict[str, int]:
        raise _unimplemented("data_validation", "Phase 2", "Record validation")


class UnimplementedFeatureService:
    """Satisfies ``FeatureService``; ships in Phase 3."""

    async def build_features(
        self, *, zone_ids: list[UUID], as_of: datetime
    ) -> dict[UUID, dict[str, float | None]]:
        raise _unimplemented("feature_engineering", "Phase 3", "Feature construction")


class UnimplementedPredictionService:
    """Satisfies ``PredictionService``; ships in Phase 3.

    No model artefact exists, so ``model_version`` reports ``unavailable``
    rather than a version string implying a trained model is loaded.
    """

    @property
    def model_version(self) -> str:
        return "unavailable"

    async def predict_zone(self, zone_id: UUID, *, as_of: datetime) -> ZoneRiskPrediction:
        raise _unimplemented("risk_prediction", "Phase 3", "Zone flood-risk prediction")

    async def predict_city(self, *, as_of: datetime) -> RiskSurface:
        raise _unimplemented("risk_prediction", "Phase 3", "City-wide risk surface generation")


class UnimplementedImpactService:
    """Satisfies ``ImpactService``; ships in Phase 4."""

    async def assess(
        self, surface: RiskSurface, *, risk_threshold: float = 0.5
    ) -> ImpactAssessment:
        raise _unimplemented("impact_analysis", "Phase 4", "Road and access impact assessment")


class UnimplementedRecommendationService:
    """Satisfies ``RecommendationService``; ships in Phase 4."""

    async def recommend(
        self, surface: RiskSurface, impact: ImpactAssessment
    ) -> list[RecommendedAction]:
        raise _unimplemented("recommendations", "Phase 4", "Municipal action recommendation")


class UnimplementedAlertService:
    """Satisfies ``AlertService``; ships in Phase 5."""

    async def evaluate(self, surface: RiskSurface) -> list[str]:
        raise _unimplemented("alerts", "Phase 5", "Threshold alert evaluation")
