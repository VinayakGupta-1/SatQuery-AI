"""The structured shape a query-understanding provider must produce.

Nothing downstream ever sees free-form model text. A provider returns an
:class:`AgentTaskPlan` or it fails, which is what makes the rest of the
pipeline able to treat model output as data rather than as instructions.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentTaskPlan(BaseModel):
    """A structured reading of one natural-language request.

    This is a *proposal*. Nothing here is trusted: the tool is checked against
    the registry, the parameters are checked against that tool's declared
    schema, and the imagery is checked by the deterministic validator before
    anything runs.
    """

    #: Short task label, e.g. ``ndvi`` or ``change_detection``.
    task: str | None = None
    #: Broad family, e.g. ``index_computation`` or ``temporal_analysis``.
    operation: str | None = None
    #: The registry ``tool_id`` the provider believes applies, if any.
    tool: str | None = None
    #: How sure the provider is, in ``[0, 1]``.
    confidence: float = 0.0
    #: Parameters extracted from the wording, e.g. a threshold.
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: Input kinds the task needs, e.g. ``["raster"]``.
    required_inputs: list[str] = Field(default_factory=list)
    #: Entities named in the query, e.g. ``["buildings"]``.
    objects: list[str] = Field(default_factory=list)
    #: The output the user asked for, e.g. ``map`` or ``statistics``.
    requested_output: str | None = None
    #: ``single`` or ``bi_temporal`` when the wording implies it.
    temporal_requirement: str | None = None
    #: Set when the request cannot be acted on without more information.
    clarification: str | None = None
    #: Which provider produced this, for the audit trail.
    provider: str = "rules"
    #: Short human-readable justification. Never executed, only displayed.
    reasoning: str = ""

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        """A provider that reports 7.0 or -1 is clamped, not trusted."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, max(0.0, numeric))

    @field_validator("parameters", mode="before")
    @classmethod
    def _coerce_parameters(cls, value: Any) -> dict[str, Any]:
        """A provider that returns a list or a string gets an empty dict."""
        return value if isinstance(value, dict) else {}

    @field_validator("required_inputs", "objects", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return []

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification)


class GuardDecision(BaseModel):
    """What the safety guard did to a provider's proposal."""

    plan: AgentTaskPlan
    #: Tool ids the provider proposed that the registry does not sanction.
    rejected_tools: list[str] = Field(default_factory=list)
    #: Parameter names dropped because the tool does not declare them.
    rejected_parameters: list[str] = Field(default_factory=list)
    #: Human-readable notes for the explanation block.
    notes: list[str] = Field(default_factory=list)

    @property
    def modified(self) -> bool:
        return bool(self.rejected_tools or self.rejected_parameters)


__all__ = ["AgentTaskPlan", "GuardDecision"]
