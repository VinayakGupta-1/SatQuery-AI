"""Health and capability endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import BackendInfo, HealthResponse
from app.registry.registry import get_all_tools
from app.tools.binding import implemented_tool_ids
from app.tools.raster.io import backend_report

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report liveness and which raster capabilities are actually available.

    The backend block is genuinely useful in the field: it says whether GDAL is
    present, and therefore whether compressed products can be read at all.
    """
    return HealthResponse(
        status="ok",
        registered_tools=len(get_all_tools()),
        implemented_tools=implemented_tool_ids(),
        backend=BackendInfo(**backend_report()),
    )
