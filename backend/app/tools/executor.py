"""The entry point the Execution Orchestrator uses to run a real tool.

This is the boundary the controller stops at. Everything above it reasons
about tasks; everything below it touches pixels. The executor performs no
policy checks of its own -- the orchestrator has already verified the tool
against the Registry -- it only locates the bound implementation and runs it.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import ToolExecutionError, ToolOutput, ToolRequest
from app.tools.binding import get_implementation, implemented_tool_ids


class ToolNotImplementedError(ToolExecutionError):
    """A registered tool has no implementation bound to it yet."""


class ToolExecutor:
    """Runs the implementation bound to a registered tool."""

    def run(
        self,
        tool_id: str,
        parameters: dict[str, Any] | None = None,
        input_references: list[str] | None = None,
        output_directory: str | None = None,
    ) -> ToolOutput:
        """Execute ``tool_id`` and return its structured output."""
        implementation = get_implementation(tool_id)
        if implementation is None:
            raise ToolNotImplementedError(
                f"Tool '{tool_id}' is registered but has no execution implementation "
                f"yet. Implemented tools: {implemented_tool_ids()}."
            )

        request = ToolRequest(
            tool_id=tool_id,
            parameters=parameters or {},
            input_references=input_references or [],
            output_directory=output_directory,
        )
        return implementation.execute(request)
