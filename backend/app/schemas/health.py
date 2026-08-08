"""Health and readiness schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel

HealthState = Literal["ok", "degraded", "unavailable", "disabled"]


class DependencyHealth(APIModel):
    name: str
    state: HealthState
    latency_ms: float | None = None
    detail: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class HealthResponse(APIModel):
    status: HealthState
    service: str
    version: str
    environment: str
    checked_at: datetime


class DatabaseHealthResponse(HealthResponse):
    """``GET /health/db`` — verifies connectivity *and* the PostGIS extension.

    A plain ``SELECT 1`` is not sufficient here: the whole platform depends on
    PostGIS being installed, so the probe asserts that too.
    """

    database: DependencyHealth
    postgis: DependencyHealth


class ReadinessResponse(HealthResponse):
    dependencies: list[DependencyHealth]
