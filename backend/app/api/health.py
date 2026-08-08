"""Liveness and dependency health endpoints.

Mounted outside the versioned prefix: orchestrators probe these, and probe
URLs should not churn when the API version does.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import CacheDep, SessionDep, SettingsDep
from app.core.version import SERVICE_VERSION
from app.schemas.health import (
    DatabaseHealthResponse,
    DependencyHealth,
    HealthResponse,
    ReadinessResponse,
)

router = APIRouter(tags=["health"])


def _base(settings: SettingsDep, status: str) -> dict:
    return {
        "status": status,
        "service": settings.project_name,
        "version": SERVICE_VERSION,
        "environment": settings.environment,
        "checked_at": datetime.now(UTC),
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 whenever the process is running. Touches no dependencies.",
)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(**_base(settings, "ok"))


async def _check_database(
    session: SessionDep, timeout: float
) -> tuple[DependencyHealth, DependencyHealth]:
    """Probe connectivity and the PostGIS extension in one round trip.

    PostGIS is checked explicitly because a reachable PostgreSQL without the
    extension would fail every geospatial query at runtime — a state a plain
    ``SELECT 1`` reports as healthy.
    """
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            session.execute(
                text(
                    "SELECT version() AS pg_version, "
                    "       (SELECT extversion FROM pg_extension WHERE extname = 'postgis') "
                    "       AS postgis_version"
                )
            ),
            timeout=timeout,
        )
        row = result.one()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        database = DependencyHealth(
            name="postgresql",
            state="ok",
            latency_ms=latency_ms,
            metadata={"server_version": row.pg_version.split(",")[0]},
        )
        if row.postgis_version is None:
            postgis = DependencyHealth(
                name="postgis",
                state="unavailable",
                detail="The postgis extension is not installed in this database.",
            )
        else:
            postgis = DependencyHealth(
                name="postgis",
                state="ok",
                metadata={"version": row.postgis_version},
            )
        return database, postgis

    except TimeoutError:
        return (
            DependencyHealth(
                name="postgresql",
                state="unavailable",
                detail=f"Query exceeded the {timeout}s health timeout.",
            ),
            DependencyHealth(name="postgis", state="unavailable", detail="Database unreachable."),
        )
    except Exception as exc:  # noqa: BLE001 - a probe reports failures, never raises
        return (
            DependencyHealth(name="postgresql", state="unavailable", detail=str(exc)),
            DependencyHealth(name="postgis", state="unavailable", detail="Database unreachable."),
        )


@router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    summary="Database and PostGIS probe",
    description=(
        "Verifies that PostgreSQL is reachable and that the PostGIS extension is installed. "
        "Always returns 200; inspect the per-dependency `state` fields."
    ),
)
async def health_db(settings: SettingsDep, session: SessionDep) -> DatabaseHealthResponse:
    database, postgis = await _check_database(session, settings.db_health_timeout_seconds)
    overall = "ok" if database.state == "ok" and postgis.state == "ok" else "unavailable"
    return DatabaseHealthResponse(**_base(settings, overall), database=database, postgis=postgis)


async def _check_cache(cache: CacheDep, timeout: float) -> DependencyHealth:
    if not cache.enabled:
        return DependencyHealth(
            name="redis", state="disabled", detail="REDIS_ENABLED is false; caching is bypassed."
        )
    started = time.perf_counter()
    try:
        await cache.ping(timeout=timeout)
        return DependencyHealth(
            name="redis", state="ok", latency_ms=round((time.perf_counter() - started) * 1000, 2)
        )
    except Exception as exc:  # noqa: BLE001
        # Degraded, not unavailable: the API still serves reads without a cache.
        return DependencyHealth(name="redis", state="degraded", detail=str(exc))


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Aggregates every dependency check. `degraded` means optional dependencies failed.",
)
async def health_ready(
    settings: SettingsDep, session: SessionDep, cache: CacheDep
) -> ReadinessResponse:
    database, postgis = await _check_database(session, settings.db_health_timeout_seconds)
    redis = await _check_cache(cache, settings.redis_health_timeout_seconds)
    dependencies = [database, postgis, redis]

    if any(dep.state == "unavailable" for dep in dependencies):
        overall = "unavailable"
    elif any(dep.state == "degraded" for dep in dependencies):
        overall = "degraded"
    else:
        overall = "ok"

    return ReadinessResponse(**_base(settings, overall), dependencies=dependencies)
