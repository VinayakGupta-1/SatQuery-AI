"""Binding between Registry entries and their real implementations.

The Registry declares *what* a tool is and what it may be given. This module
declares *which code actually runs it*. The two are deliberately separate, and
a binding is only ever valid when a Registry entry with the same ``tool_id``
exists -- so an implementation can never smuggle in a capability the Registry
has not sanctioned.

A registered tool with no binding is not an error: it is a tool whose
implementation has not been built yet. A bound tool can also be switched off
-- satellite VQA until an operator enables it, for instance. Both states are
reported honestly by the orchestrator rather than papered over with a
placeholder result, and both count as "not implemented" everywhere a caller
asks what can actually run.
"""

from __future__ import annotations

from app.registry.registry import get_tool
from app.tools.base import RemoteSensingTool
from app.tools.change.bitemporal import BiTemporalChangeDetectionTool
from app.tools.detection.tool import RegionDetectionTool
from app.tools.fusion.tool import OpticalSARFusionTool
from app.tools.indices.ndbi import NDBITool
from app.tools.indices.ndvi import NDVITool
from app.tools.indices.ndwi import NDWITool
from app.tools.landcover.tool import LandCoverClassificationTool
from app.tools.sar.tool import SARAnalysisTool
from app.tools.vlm.captioning import ImageCaptioningTool
from app.tools.vlm.change_vqa import ChangeVQATool
from app.tools.vlm.vqa import SatelliteVQATool

# ============================================================
# BOUND IMPLEMENTATIONS
# ============================================================
_IMPLEMENTATIONS: list[RemoteSensingTool] = [
    # Deterministic engines.
    NDVITool(),
    NDWITool(),
    NDBITool(),
    BiTemporalChangeDetectionTool(),
    LandCoverClassificationTool(),
    RegionDetectionTool(),
    SARAnalysisTool(),
    OpticalSARFusionTool(),
    # The vision-language model core.
    SatelliteVQATool(),
    ImageCaptioningTool(),
    ChangeVQATool(),
]

IMPLEMENTATIONS: dict[str, RemoteSensingTool] = {
    implementation.tool_id: implementation for implementation in _IMPLEMENTATIONS
}


class BindingError(Exception):
    """Raised when a binding does not correspond to a registered tool."""


def get_implementation(tool_id: str) -> RemoteSensingTool | None:
    """Return the implementation bound to ``tool_id``, available or not."""
    return IMPLEMENTATIONS.get(tool_id)


def has_implementation(tool_id: str) -> bool:
    """Return True when ``tool_id`` is bound *and* can run right now."""
    implementation = IMPLEMENTATIONS.get(tool_id)
    return implementation is not None and implementation.available()


def implemented_tool_ids() -> list[str]:
    """Return the sorted ids of every tool that can actually be executed."""
    return sorted(tool_id for tool_id in IMPLEMENTATIONS if has_implementation(tool_id))


def unavailable_reason(tool_id: str) -> str | None:
    """Say why ``tool_id`` cannot run, or ``None`` when it can."""
    implementation = IMPLEMENTATIONS.get(tool_id)
    if implementation is None:
        return "No implementation is bound to this capability yet."
    if implementation.available():
        return None
    return implementation.unavailable_reason() or "It is switched off in this deployment."


def verify_bindings() -> None:
    """Check every binding against the Registry.

    Raises :class:`BindingError` when an implementation claims a ``tool_id``
    that the Registry does not define, or when the two disagree about identity.
    """
    for tool_id, implementation in IMPLEMENTATIONS.items():
        if not tool_id:
            raise BindingError(
                f"{type(implementation).__name__} does not declare a tool_id."
            )
        definition = get_tool(tool_id)
        if definition is None:
            raise BindingError(
                f"{type(implementation).__name__} is bound to '{tool_id}', which is "
                "not present in the registry. Register the tool before binding it."
            )
        if implementation.tool_id != definition.tool_id:
            raise BindingError(
                f"Binding mismatch: {type(implementation).__name__} reports "
                f"'{implementation.tool_id}' but is keyed as '{tool_id}'."
            )
