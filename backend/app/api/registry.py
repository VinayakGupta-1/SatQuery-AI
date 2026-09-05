"""Registry endpoints -- what this system is actually able to do.

Exposing the registry matters for more than documentation: it is the honest
statement of the system's capability boundary. ``implemented`` distinguishes a
tool that will run from one that is declared but not yet built.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import ToolSummary
from app.registry.registry import get_all_tools, get_tool
from app.tools.binding import has_implementation

router = APIRouter(prefix="/api/tools", tags=["registry"])


def summarise(tool) -> ToolSummary:
    """Shape one registry entry for the API. Shared with /capabilities."""
    return ToolSummary(
        tool_id=tool.tool_id,
        name=tool.name,
        description=tool.description,
        tool_type=tool.tool_type.value,
        version=tool.version,
        output_type=tool.output_type.value,
        supported_modalities=list(tool.supported_modalities),
        required_bands=list(tool.required_bands),
        min_images=tool.min_images,
        max_images=tool.max_images,
        requires_temporal_pair=tool.requires_temporal_pair,
        parameters=dict(tool.parameters),
        enabled=tool.enabled,
        implemented=has_implementation(tool.tool_id),
    )


@router.get("", response_model=list[ToolSummary])
def list_tools(implemented_only: bool = False) -> list[ToolSummary]:
    """List every registered tool.

    Pass ``implemented_only=true`` to see only the tools that can actually run.
    """
    tools = [summarise(tool) for tool in get_all_tools()]
    if implemented_only:
        tools = [tool for tool in tools if tool.implemented]
    return tools


@router.get("/{tool_id}", response_model=ToolSummary)
def read_tool(tool_id: str) -> ToolSummary:
    """Describe one registered tool, including the parameters it accepts."""
    tool = get_tool(tool_id)
    if tool is None:
        raise HTTPException(404, f"No registered tool with id '{tool_id}'.")
    return summarise(tool)
