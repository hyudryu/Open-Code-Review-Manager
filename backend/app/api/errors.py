"""Structured error handling (SPEC §29).

Every API error answers: what failed, why, what next, sanitized detail —
never stack traces, never secrets.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, redact_text
from app.services.errors import ServiceError

logger = get_logger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"loc": [str(part) for part in err.get("loc", [])], "msg": err.get("msg", "")}
            for err in exc.errors()[:10]
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "The request payload is not valid.",
                    "detail": details,
                    "next_action": "Fix the highlighted fields and retry.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_api_error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "detail": redact_text(f"{type(exc).__name__}: {exc}")[:300],
                    "next_action": "Check Diagnostics for details; retry the action.",
                }
            },
        )
