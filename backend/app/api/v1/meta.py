"""System metadata: what this deployment can actually do."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.version import API_VERSION, SERVICE_VERSION
from app.schemas.meta import AreaOfInterest, SystemMeta
from app.services.registry import MODULES

router = APIRouter(tags=["meta"])


@router.get(
    "/meta",
    response_model=SystemMeta,
    summary="Deployment capabilities and area of interest",
    description=(
        "Reports the implementation state of every architectural module. The frontend renders "
        "this directly so the UI can never claim a capability the backend lacks."
    ),
)
async def get_meta(settings: SettingsDep) -> SystemMeta:
    return SystemMeta(
        service=settings.project_name,
        version=SERVICE_VERSION,
        environment=settings.environment,
        api_version=API_VERSION,
        area_of_interest=AreaOfInterest(
            city_name=settings.city_name,
            country_code=settings.city_country_code,
            bbox=settings.city_bbox,
            center=settings.city_center,
            default_zoom=settings.default_map_zoom,
        ),
        modules=list(MODULES),
        llm_configured=settings.llm_configured,
        llm_provider=settings.llm_provider,
    )
