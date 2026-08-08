"""Application exception hierarchy.

Every error the API can return deliberately maps to one of these types. The
handlers in :mod:`app.core.error_handlers` translate them into a single
machine-readable error envelope so the frontend never has to guess.
"""

from __future__ import annotations

from typing import Any


class UrbanPulseError(Exception):
    """Base class for all application errors."""

    status_code: int = 500
    error_code: str = "internal_error"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class ConfigurationError(UrbanPulseError):
    """A required piece of configuration is missing or invalid."""

    status_code = 500
    error_code = "configuration_error"
    default_message = "The service is misconfigured."


class NotFoundError(UrbanPulseError):
    status_code = 404
    error_code = "not_found"
    default_message = "The requested resource does not exist."


class ValidationError(UrbanPulseError):
    status_code = 422
    error_code = "validation_error"
    default_message = "The request payload is invalid."


class ExternalServiceError(UrbanPulseError):
    """An upstream data provider or LLM API failed."""

    status_code = 502
    error_code = "external_service_error"
    default_message = "An upstream service failed."


class ServiceUnavailableError(UrbanPulseError):
    """A dependency (database, cache) is currently unreachable."""

    status_code = 503
    error_code = "service_unavailable"
    default_message = "A required dependency is unavailable."


class DataUnavailableError(UrbanPulseError):
    """The requested analysis cannot be produced from available data.

    This is central to the product's honesty guarantee: when the underlying
    datasets are missing, the system says so explicitly instead of returning a
    fabricated value.
    """

    status_code = 409
    error_code = "data_unavailable"
    default_message = "The data required to answer this request has not been ingested."


class NotImplementedFeatureError(UrbanPulseError):
    """A module exists as an interface but has no implementation yet.

    Returning HTTP 501 keeps unfinished capabilities visible rather than
    disguising them behind placeholder responses.
    """

    status_code = 501
    error_code = "not_implemented"
    default_message = "This capability is defined but not implemented yet."

    def __init__(
        self,
        message: str | None = None,
        *,
        module: str | None = None,
        planned_phase: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        if module:
            merged["module"] = module
        if planned_phase:
            merged["planned_phase"] = planned_phase
        super().__init__(message, details=merged)
