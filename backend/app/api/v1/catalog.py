"""Data catalogue endpoints.

These are the provenance surface: every dataset the platform holds, who
published it, under what licence, and whether its values are observed or
simulated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CatalogRepositoryDep
from app.core.exceptions import NotFoundError
from app.models.provenance import DataSourceKind
from app.schemas.catalog import CatalogSummary, DataSourceRead, IngestionRunRead

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get(
    "/sources",
    response_model=list[DataSourceRead],
    summary="List registered data sources",
    description=(
        "Every dataset registered for this deployment. Clients must display sources whose "
        "`origin` is `simulated` distinctly from observed data."
    ),
)
async def list_sources(
    repository: CatalogRepositoryDep,
    kind: Annotated[DataSourceKind | None, Query(description="Filter by dataset kind.")] = None,
    active_only: Annotated[bool, Query(description="Exclude deactivated sources.")] = False,
) -> list[DataSourceRead]:
    sources = await repository.list_data_sources(kind=kind, active_only=active_only)
    return [DataSourceRead.model_validate(source) for source in sources]


@router.get(
    "/sources/{slug}",
    response_model=DataSourceRead,
    summary="Fetch one data source by slug",
)
async def get_source(slug: str, repository: CatalogRepositoryDep) -> DataSourceRead:
    source = await repository.get_data_source_by_slug(slug)
    if source is None:
        raise NotFoundError(f"No data source registered with slug '{slug}'.")
    return DataSourceRead.model_validate(source)


@router.get(
    "/ingestion-runs",
    response_model=list[IngestionRunRead],
    summary="Recent ingestion runs",
    description="Audit trail of ingestion attempts, most recent first.",
)
async def list_runs(
    repository: CatalogRepositoryDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IngestionRunRead]:
    runs = await repository.list_ingestion_runs(limit=limit)
    return [IngestionRunRead.model_validate(run) for run in runs]


@router.get(
    "/summary",
    response_model=CatalogSummary,
    summary="Row counts per dataset table",
    description=(
        "Exact counts of what has been ingested. Zeros are meaningful: they mean no data has "
        "been loaded, not that the query failed."
    ),
)
async def get_summary(repository: CatalogRepositoryDep) -> CatalogSummary:
    return await repository.summary()
