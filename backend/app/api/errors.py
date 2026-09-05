"""One error shape for the whole API.

Two things matter here.

*A client always gets the same envelope.* Whether a request failed validation,
named a missing task, or hit a bug, the body has ``error``, ``code``,
``message`` and ``detail``. A frontend writes one error path, not five.

*A stack trace never reaches the client.* An unhandled exception is logged in
full on the server and returned as a generic message with a correlation id.
Internal paths, module names and SQL-ish detail are exactly what an attacker
wants and exactly what a user cannot act on.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.ingestion import IngestionError
from app.config.logging_config import get_logger
from app.storage.artifacts import StorageError
from app.tools.base import ToolExecutionError

logger = get_logger("api")


class FieldError(BaseModel):
    """Field-level context for a rejected request."""

    field: str
    message: str


class ErrorResponse(BaseModel):
    """The body of every non-2xx response.

    ``detail`` keeps FastAPI's conventional meaning -- a human-readable string
    -- so existing clients continue to work unchanged. The structured parts
    (``code``, ``fields``, ``incident_id``) are added alongside it rather than
    in place of it.
    """

    error: bool = True
    #: Stable machine-readable code, e.g. ``invalid_upload``.
    code: str
    #: Human-readable, safe to display. Identical to ``detail``.
    message: str
    #: The same text as ``message``; kept for FastAPI compatibility.
    detail: str
    #: Per-field context, when the failure was field-level.
    fields: list[FieldError] = Field(default_factory=list)
    #: Present only on unexpected failures; quote it when reporting a bug.
    incident_id: str | None = None


def _json(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(
            code=code, message=message, detail=message, **extra
        ).model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers that give the API its single error shape."""

    @app.exception_handler(RequestValidationError)
    async def _request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """A malformed request: wrong field types, missing form fields."""
        fields = [
            FieldError(
                field=".".join(str(part) for part in error.get("loc", ())),
                message=str(error.get("msg", "")),
            )
            for error in exc.errors()
        ]
        return _json(
            422,
            "invalid_request",
            "The request did not match the expected schema.",
            fields=fields,
        )

    @app.exception_handler(IngestionError)
    async def _ingestion(request: Request, exc: IngestionError) -> JSONResponse:
        """An upload that could not be accepted. The message is user-facing."""
        return _json(400, "invalid_upload", str(exc))

    @app.exception_handler(StorageError)
    async def _storage(request: Request, exc: StorageError) -> JSONResponse:
        incident = uuid.uuid4().hex[:12]
        logger.error(
            "storage failure",
            extra={"incident_id": incident, "path": request.url.path},
            exc_info=exc,
        )
        return _json(
            500,
            "storage_error",
            "The server could not store or retrieve a file for this task.",
            incident_id=incident,
        )

    @app.exception_handler(ToolExecutionError)
    async def _tool_execution(
        request: Request, exc: ToolExecutionError
    ) -> JSONResponse:
        """A tool refused to produce a result. Its message explains why."""
        return _json(422, "execution_error", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            400: "bad_request",
            404: "not_found",
            405: "method_not_allowed",
            410: "gone",
            413: "payload_too_large",
        }
        return _json(
            exc.status_code,
            codes.get(exc.status_code, "http_error"),
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """The catch-all. Full detail to the log, none of it to the client."""
        incident = uuid.uuid4().hex[:12]
        logger.error(
            "unhandled exception",
            extra={
                "incident_id": incident,
                "path": request.url.path,
                "method": request.method,
            },
            exc_info=exc,
        )
        return _json(
            500,
            "internal_error",
            "The server encountered an unexpected error. The incident id can "
            "be quoted when reporting this.",
            incident_id=incident,
        )


__all__ = ["ErrorResponse", "register_error_handlers"]
