"""Shared response primitives."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    """Base for every response model."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorDetail(APIModel):
    code: str = Field(description="Stable machine-readable error identifier.")
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(APIModel):
    """The single error envelope returned by every non-2xx response."""

    error: ErrorDetail


class GeoJSONFeature(APIModel):
    type: Literal["Feature"] = "Feature"
    id: str | None = None
    geometry: dict[str, Any] | None
    properties: dict[str, Any] = Field(default_factory=dict)


class GeoJSONFeatureCollection(APIModel):
    """RFC 7946 feature collection, consumed directly by MapLibre GL."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature] = Field(default_factory=list)
    #: Non-standard but harmless: lets the client show provenance and counts.
    metadata: dict[str, Any] = Field(default_factory=dict)
