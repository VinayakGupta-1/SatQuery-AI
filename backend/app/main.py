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
from app.config.settings import get_settings
from app.tools.binding import verify_bindings

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


def create_app() -> FastAPI:
    """Build the application. Kept as a factory so tests get a fresh instance."""
    settings = get_settings()

    # Fail at startup, not mid-request, if a tool is bound to a registry entry
    # that does not exist.
    verify_bindings()

    app = FastAPI(
        title="SatQuery AI",
        description=DESCRIPTION,
        version="0.1.0",
    )

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

    return app


app = create_app()
