"""UrbanPulse API application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1.router import api_router
from app.cache.redis_cache import close_cache, init_cache
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.version import SERVICE_VERSION
from app.db.session import dispose_engine, init_engine

logger = get_logger(__name__)

DESCRIPTION = """\
UrbanPulse predicts urban flooding and waterlogging risk and the impact it has on roads
and traffic.

**How to read this API**

* `/health`, `/health/db` and `/health/ready` are unversioned probes.
* `/api/v1/meta` reports which architectural modules are actually implemented in this
  deployment.
* `/api/v1/catalog/*` exposes dataset provenance — every stored record is attributable to a
  registered source marked `observed`, `derived` or `simulated`.
* `/api/v1/geo/*` serves GeoJSON straight from PostGIS.
* Analysis routes return **501 Not Implemented** until their engines ship. They never return
  sample or placeholder values.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the lifetime of the connection pools."""
    settings: Settings = app.state.settings
    init_engine(settings)
    init_cache(settings)
    logger.info(
        "application_started",
        environment=settings.environment,
        version=SERVICE_VERSION,
        city=settings.city_name,
        redis_enabled=settings.redis_enabled,
        llm_configured=settings.llm_configured,
    )
    try:
        yield
    finally:
        await close_cache()
        await dispose_engine()
        logger.info("application_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.project_name,
        description=DESCRIPTION,
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    # Order matters: CORS is added last so it runs first and can attach headers
    # to error responses produced further down the stack.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": settings.project_name,
            "version": SERVICE_VERSION,
            "docs": "/docs",
            "api": settings.api_v1_prefix,
        }

    return app


app = create_app()
