"""SatQuery AI -- FastAPI application.

Run it with::

    uvicorn app.main:app --reload

Interactive documentation is then at http://127.0.0.1:8000/docs

The HTTP layer is intentionally thin. It ingests uploads, hands them to
:class:`~app.controller.pipeline.SatQueryPipeline`, and shapes the result. No
remote-sensing decision is made here, so the API can be replaced without
touching the controller and the controller stays testable without HTTP.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import registry as registry_routes
from app.api import tasks as task_routes
from app.api import validation as system_routes
from app.api.errors import ErrorResponse, register_error_handlers
from app.config.logging_config import configure_logging, get_logger
from app.config.settings import get_settings
from app.storage.artifacts import get_artifact_store
from app.tools.binding import implemented_tool_ids, verify_bindings
from app.tools.raster.io import backend_report

logger = get_logger("startup")

DESCRIPTION = """
Ask questions about satellite imagery in plain language.

A request passes through ten deterministic stages: the query is understood and
classified, a plan and its input requirements are derived, the imagery is
validated against them, a tool is selected **from a controlled registry**, its
parameters are resolved, execution is authorised, the tool runs, and the result
is integrated into one response shape.

Two properties are deliberate:

* **No tool runs that is not registered.** The registry is the capability
  boundary, and `/api/tools` publishes it.
* **Nothing is fabricated.** A tool that has no implementation reports that
  plainly instead of returning a placeholder result.
"""


OPENAPI_TAGS = [
    {
        "name": "system",
        "description": (
            "Liveness and capability discovery. `/capabilities` is generated "
            "from the tool registry, so it is the authoritative statement of "
            "what this deployment can do."
        ),
    },
    {
        "name": "analysis",
        "description": (
            "Submit imagery with a natural-language question. `/analyze` runs "
            "the full pipeline; `/analyze/validate` stops before execution and "
            "reports only whether the request would run."
        ),
    },
    {
        "name": "registry",
        "description": "The controlled set of tools that are allowed to run.",
    },
]

#: Attached to every route so the error envelope appears in the schema.
DEFAULT_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": "The request could not be accepted."},
    404: {"model": ErrorResponse, "description": "No such task, tool or artifact."},
    422: {"model": ErrorResponse, "description": "Validation or execution refused the request."},
    500: {"model": ErrorResponse, "description": "Unexpected server error."},
}


def create_app() -> FastAPI:
    """Build the application. Kept as a factory so tests get a fresh instance."""
    settings = get_settings()
    configure_logging()

    # Fail at startup, not mid-request, if a tool is bound to a registry entry
    # that does not exist.
    verify_bindings()
    # Create the storage roots now so the first upload is not the thing that
    # discovers the directory is unwritable.
    get_artifact_store()

    app = FastAPI(
        title="SatQuery AI",
        description=DESCRIPTION,
        version="1.0.0",
        openapi_tags=OPENAPI_TAGS,
        responses=DEFAULT_RESPONSES,
    )

    # Installed before the routers so every route inherits the one error shape.
    register_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system_routes.router)
    app.include_router(registry_routes.router)
    app.include_router(task_routes.router)
    app.include_router(task_routes.analysis_router)

    logger.info(
        "SatQuery started",
        extra={
            "executable_tools": len(implemented_tool_ids()),
            "agent_provider": settings.resolved_agent_provider,
            "raster_backend": backend_report()["raster_backend"],
        },
    )
    return app


app = create_app()
