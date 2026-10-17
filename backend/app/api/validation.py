"""Health and capability endpoints.

``/capabilities`` is generated from the registry on every call rather than
maintained by hand. That is the point: a tool that is registered appears here,
a tool that cannot run appears with ``implemented`` false, and there is no
second list that can drift out of step with what the system can actually do.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.registry import summarise
from app.api.schemas import BackendInfo, CapabilitiesResponse, HealthResponse
from app.config.settings import get_settings
from app.registry.registry import get_all_tools
from app.tools.binding import implemented_tool_ids
from app.tools.raster.io import backend_report

router = APIRouter(tags=["system"])

#: The same version the FastAPI app reports: one definition, in app/__init__.
APP_VERSION = __version__


@router.get("/health", response_model=HealthResponse)
@router.get("/api/health", response_model=HealthResponse)
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


@router.get("/capabilities", response_model=CapabilitiesResponse)
@router.get("/api/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    """Describe everything this deployment can currently do.

    Built from the tool registry, the bound implementations and the live
    configuration, so it never claims a capability the server cannot deliver.
    A frontend can drive its whole UI from this one call.
    """
    settings = get_settings()
    tools = [summarise(tool) for tool in get_all_tools()]
    return CapabilitiesResponse(
        version=APP_VERSION,
        executable=implemented_tool_ids(),
        tools=tools,
        accepted_formats=list(settings.allowed_extensions),
        max_upload_bytes=settings.max_upload_bytes,
        max_images_per_task=settings.max_images_per_task,
        agent_provider=settings.resolved_agent_provider,
        agent_llm_enabled=settings.resolved_agent_provider in {"hosted", "ollama"},
        vlm_provider=settings.vqa_provider if settings.vqa_available else None,
        vlm_local=settings.vqa_available and settings.vqa_is_local,
        # Fetching reads remote cloud-optimised GeoTIFFs, which needs GDAL.
        auto_fetch=settings.fetch_enabled and backend_report()["supports_compressed_geotiff"],
        backend=BackendInfo(**backend_report()),
    )
