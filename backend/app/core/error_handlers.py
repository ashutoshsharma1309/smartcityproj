"""Exception handlers producing a single, consistent error envelope.

Every non-2xx response from the API has the shape::

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import UrbanPulseError
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


def _envelope(
    *,
    code: str,
    message: str,
    details: dict | None = None,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id_ctx.get(),
            }
        },
    )


async def urbanpulse_error_handler(_request: Request, exc: UrbanPulseError) -> JSONResponse:
    log = logger.bind(error_code=exc.error_code, status_code=exc.status_code)
    if exc.status_code >= 500 and exc.status_code != status.HTTP_501_NOT_IMPLEMENTED:
        log.error("application_error", message=exc.message, details=exc.details)
    else:
        log.info("application_error", message=exc.message, details=exc.details)
    return _envelope(
        code=exc.error_code,
        message=exc.message,
        details=exc.details,
        status_code=exc.status_code,
    )


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _envelope(
        code="http_error",
        message=str(exc.detail),
        status_code=exc.status_code,
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _envelope(
        code="validation_error",
        message="Request validation failed.",
        details={"errors": exc.errors()},
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", exc_type=type(exc).__name__)
    return _envelope(
        code="internal_error",
        message="An unexpected error occurred.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(UrbanPulseError, urbanpulse_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
