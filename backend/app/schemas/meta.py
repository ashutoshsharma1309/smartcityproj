"""System capability metadata.

``GET /api/v1/meta`` is the honesty endpoint: it reports, per module, whether a
capability is actually implemented. The frontend renders this directly, so the
dashboard can never imply a capability the backend does not have.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel

ModuleState = Literal["implemented", "interface_only", "not_configured"]


class ModuleStatus(APIModel):
    key: str
    name: str
    state: ModuleState
    description: str
    planned_phase: str | None = Field(
        default=None, description="Roadmap phase that will implement this module."
    )


class AreaOfInterest(APIModel):
    city_name: str
    country_code: str
    #: min_lon, min_lat, max_lon, max_lat in EPSG:4326.
    bbox: list[float]
    #: lon, lat.
    center: list[float]
    default_zoom: float


class SystemMeta(APIModel):
    service: str
    version: str
    environment: str
    api_version: str
    area_of_interest: AreaOfInterest
    modules: list[ModuleStatus]
    #: True only when an LLM provider and credentials are both configured.
    llm_configured: bool
    llm_provider: str
