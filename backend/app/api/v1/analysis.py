"""Risk, impact, recommendation and explanation endpoints.

Every route here is wired to a real service object and a frozen response
schema, so the OpenAPI contract is complete and the frontend can be built
against it. The underlying engines are not implemented yet, so each call
returns HTTP 501 naming the module and the roadmap phase.

Returning 501 rather than sample output is the point: a caller can tell the
difference between "no risk" and "risk was never computed".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query

from app.api.deps import (
    ExplanationServiceDep,
    ImpactServiceDep,
    IngestionServiceDep,
    PredictionServiceDep,
    RecommendationServiceDep,
)
from app.schemas.catalog import IngestionRunRead
from app.schemas.common import ErrorResponse
from app.schemas.risk import (
    ExplanationRequest,
    ExplanationResponse,
    ImpactAssessment,
    RecommendedAction,
    RiskSurface,
    ZoneRiskPrediction,
)

NOT_IMPLEMENTED_RESPONSE = {
    501: {
        "model": ErrorResponse,
        "description": "The module is defined as an interface but is not implemented yet.",
    }
}

router = APIRouter(tags=["analysis"])


@router.post(
    "/ingestion/{source_slug}/run",
    response_model=IngestionRunRead,
    responses=NOT_IMPLEMENTED_RESPONSE,
    summary="Trigger ingestion for one data source",
)
async def run_ingestion(
    source_slug: str,
    service: IngestionServiceDep,
    window_start: Annotated[datetime | None, Query()] = None,
    window_end: Annotated[datetime | None, Query()] = None,
) -> IngestionRunRead:
    return await service.ingest(source_slug, window_start=window_start, window_end=window_end)


@router.get(
    "/risk/zones/{zone_id}",
    response_model=ZoneRiskPrediction,
    responses=NOT_IMPLEMENTED_RESPONSE,
    summary="Flood-risk prediction for one zone",
    description=(
        "Calibrated waterlogging probability with the model's own feature attributions. "
        "Computed by a gradient-boosted model, never by an LLM."
    ),
)
async def get_zone_risk(
    zone_id: UUID,
    service: PredictionServiceDep,
    as_of: Annotated[datetime | None, Query(description="Defaults to now (UTC).")] = None,
) -> ZoneRiskPrediction:
    return await service.predict_zone(zone_id, as_of=as_of or datetime.now(UTC))


@router.get(
    "/risk/surface",
    response_model=RiskSurface,
    responses=NOT_IMPLEMENTED_RESPONSE,
    summary="City-wide risk surface",
)
async def get_risk_surface(
    service: PredictionServiceDep,
    as_of: Annotated[datetime | None, Query(description="Defaults to now (UTC).")] = None,
) -> RiskSurface:
    return await service.predict_city(as_of=as_of or datetime.now(UTC))


@router.post(
    "/impact/assess",
    response_model=ImpactAssessment,
    responses=NOT_IMPLEMENTED_RESPONSE,
    summary="Assess road and access impact for a risk surface",
)
async def assess_impact(
    service: ImpactServiceDep,
    # `embed=True` keeps the body shape `{"surface": ...}`, matching
    # /recommendations, which embeds automatically because it takes two fields.
    surface: Annotated[RiskSurface, Body(embed=True)],
    risk_threshold: Annotated[float, Query(ge=0.0, le=1.0)] = 0.5,
) -> ImpactAssessment:
    return await service.assess(surface, risk_threshold=risk_threshold)


@router.post(
    "/recommendations",
    response_model=list[RecommendedAction],
    responses=NOT_IMPLEMENTED_RESPONSE,
    summary="Recommend municipal actions",
    description="Deterministic rules engine output; each action names the rule that fired.",
)
async def recommend_actions(
    service: RecommendationServiceDep,
    surface: Annotated[RiskSurface, Body()],
    impact: Annotated[ImpactAssessment, Body()],
) -> list[RecommendedAction]:
    return await service.recommend(surface, impact)


@router.post(
    "/explain",
    response_model=ExplanationResponse,
    responses={
        **NOT_IMPLEMENTED_RESPONSE,
        500: {"model": ErrorResponse, "description": "No LLM provider is configured."},
        502: {"model": ErrorResponse, "description": "The LLM provider failed."},
    },
    summary="Natural-language briefing for an existing prediction",
    description=(
        "Accepts facts already computed by the pipeline and returns prose. The service cannot "
        "produce a number of its own: its input is a validated prediction object, and the "
        "response echoes the facts it was grounded on."
    ),
)
async def explain(
    service: ExplanationServiceDep,
    request: Annotated[ExplanationRequest, Body()],
) -> ExplanationResponse:
    return await service.explain(request)
