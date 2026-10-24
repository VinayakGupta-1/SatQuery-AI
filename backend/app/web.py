"""Serve the built workspace from the analysis service itself.

A single-container deployment (a Hugging Face Space, a plain VM) has no nginx
in front, so the backend serves ``frontend/dist`` when
``SATQUERY_FRONTEND_DIST`` points at it.

Two of the workspace's routes, ``/results/{id}`` and ``/capabilities``, are
also API aliases. A browser loading one of those pages asks for HTML, so a
navigation gets the app and a ``fetch`` still gets JSON, exactly as with the
nginx configuration in ``frontend/nginx.conf``.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

#: Paths that always belong to the API, whatever the browser asks for.
API_PREFIXES = ("/api/", "/docs", "/redoc", "/openapi.json")

#: Hashed build assets never change, so they may be cached for a year.
IMMUTABLE = "public, max-age=31536000, immutable"


def _file_in(root: str, url_path: str) -> str | None:
    """The file under ``root`` that ``url_path`` names, or None.

    Anything that resolves outside ``root`` (``..``, an absolute path) is
    treated as missing rather than served.
    """
    relative = url_path.lstrip("/")
    if not relative:
        return None
    candidate = os.path.realpath(os.path.join(root, relative))
    if not candidate.startswith(root + os.sep) or not os.path.isfile(candidate):
        return None
    return candidate


def mount_frontend(app: FastAPI, dist_dir: str) -> bool:
    """Serve the workspace in ``dist_dir``; False when there is no build there."""
    root = os.path.realpath(dist_dir)
    index = os.path.join(root, "index.html")
    if not os.path.isfile(index):
        return False

    @app.middleware("http")
    async def serve_workspace(request: Request, call_next):
        path = request.url.path
        if request.method not in {"GET", "HEAD"} or path.startswith(API_PREFIXES):
            return await call_next(request)

        static = _file_in(root, path)
        if static is not None:
            response = FileResponse(static)
            if path.startswith("/assets/"):
                response.headers["Cache-Control"] = IMMUTABLE
            return response

        if "text/html" in request.headers.get("accept", ""):
            # index.html names the current hashed assets, so it must not be
            # cached across deploys.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        return await call_next(request)

    return True
