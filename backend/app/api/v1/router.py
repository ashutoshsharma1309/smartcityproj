"""Aggregates every ``/api/v1`` route."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import analysis, catalog, geospatial, meta

api_router = APIRouter()
api_router.include_router(meta.router)
api_router.include_router(catalog.router)
api_router.include_router(geospatial.router)
api_router.include_router(analysis.router)
