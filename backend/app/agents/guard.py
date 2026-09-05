"""The boundary between model output and execution.

Everything a provider returns passes through here first. The guard is
deliberately dumb and total: it does not try to understand the proposal, it
only removes anything the registry has not sanctioned.

What the guard enforces:

*Only registered tools exist.* A proposed ``tool_id`` that is not in the
registry, is disabled, or has no bound implementation is stripped. A model
cannot invent a capability by naming one.

*Only declared parameters survive.* A parameter the tool does not declare is
dropped rather than passed through, so a model cannot reach a code path the
tool never exposed.

*Nothing that looks like code is carried forward.* Values are restricted to
JSON scalars and flat lists of scalars. A dict, a callable, or a nested object
is dropped -- there is no legitimate tool parameter shaped that way, and it is
the shape an injection attempt would take.

The guard never raises on bad input. Refusing a proposal must degrade the
answer, never break the request.
"""

from __future__ import annotations

from typing import Any

from app.agents.schemas import AgentTaskPlan, GuardDecision
from app.registry.registry import get_enabled_tools, get_tool
from app.tools.binding import has_implementation

#: The only value types a tool parameter may hold.
SCALARS = (str, int, float, bool)

#: A defensive cap. No legitimate parameter is longer than this, and it stops
#: a runaway model from filling the explanation block with megabytes.
MAX_STRING_LENGTH = 512
MAX_LIST_LENGTH = 32


def allowed_tool_ids() -> list[str]:
    """Return the tools a provider is permitted to name.

    Only enabled tools with a bound implementation qualify: proposing a tool
    that cannot run is the same failure as proposing one that does not exist.
    """
    return sorted(
        tool.tool_id
        for tool in get_enabled_tools()
        if has_implementation(tool.tool_id)
    )


def _safe_value(value: Any) -> Any | None:
    """Return ``value`` if it is a permissible parameter value, else ``None``."""
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_STRING_LENGTH]
    if isinstance(value, list):
        cleaned = [
            item[:MAX_STRING_LENGTH] if isinstance(item, str) else item
            for item in value[:MAX_LIST_LENGTH]
            if isinstance(item, SCALARS)
        ]
        return cleaned or None
    return None


def guard(plan: AgentTaskPlan) -> GuardDecision:
    """Strip everything the registry has not sanctioned from ``plan``.

    Returns the cleaned plan together with a record of what was removed, so
    the API can show the user that a proposal was overruled rather than
    silently discarding it.
    """
    rejected_tools: list[str] = []
    rejected_parameters: list[str] = []
    notes: list[str] = []

    cleaned = plan.model_copy(deep=True)

    # -- the tool must be one the registry actually sanctions ----------
    if cleaned.tool:
        proposed = str(cleaned.tool).strip()
        definition = get_tool(proposed)
        if definition is None:
            rejected_tools.append(proposed)
            notes.append(
                f"Proposed tool '{proposed}' is not in the registry and was ignored."
            )
            cleaned.tool = None
        elif not definition.enabled:
            rejected_tools.append(proposed)
            notes.append(f"Proposed tool '{proposed}' is disabled and was ignored.")
            cleaned.tool = None
        elif not has_implementation(proposed):
            rejected_tools.append(proposed)
            notes.append(
                f"Proposed tool '{proposed}' is registered but has no "
                "implementation bound, so it was ignored."
            )
            cleaned.tool = None
        else:
            cleaned.tool = proposed

    # -- parameters must be declared by that tool ----------------------
    if cleaned.parameters:
        definition = get_tool(cleaned.tool) if cleaned.tool else None
        declared = set(definition.parameters) if definition else set()
        kept: dict[str, Any] = {}
        for name, value in cleaned.parameters.items():
            key = str(name)
            if key not in declared:
                rejected_parameters.append(key)
                continue
            safe = _safe_value(value)
            if safe is None:
                rejected_parameters.append(key)
                continue
            kept[key] = safe
        cleaned.parameters = kept
        if rejected_parameters:
            notes.append(
                "Dropped parameters not declared by the selected tool: "
                + ", ".join(sorted(set(rejected_parameters)))
            )

    # -- free text is displayed, never executed ------------------------
    cleaned.reasoning = str(cleaned.reasoning or "")[:MAX_STRING_LENGTH]
    if cleaned.clarification:
        cleaned.clarification = str(cleaned.clarification)[:MAX_STRING_LENGTH]

    return GuardDecision(
        plan=cleaned,
        rejected_tools=rejected_tools,
        rejected_parameters=sorted(set(rejected_parameters)),
        notes=notes,
    )


__all__ = ["allowed_tool_ids", "guard", "MAX_STRING_LENGTH", "MAX_LIST_LENGTH"]
