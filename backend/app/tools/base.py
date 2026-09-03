"""The execution contract every SatQuery remote-sensing tool implements.

The Execution Orchestrator validates a request against the Registry and then
hands it to an implementation through this contract. Keeping the contract
narrow is what lets the orchestrator stay free of tool-specific knowledge:
it only ever sees a :class:`ToolRequest` going in and a :class:`ToolOutput`
coming back.
"""

from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolExecutionError(Exception):
    """Raised when a tool cannot produce a correct result.

    Tools raise this instead of returning a degraded or approximated result,
    so a failure is always visible rather than silently plausible.
    """


class Artifact(BaseModel):
    """A file produced by a tool, such as an output raster."""

    artifact_id: str
    kind: str  # raster | vector | table | text
    path: str
    description: str = ""
    format: str | None = None


class ToolRequest(BaseModel):
    """Everything an implementation needs in order to run."""

    tool_id: str
    input_references: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_directory: str | None = None

    def resolved_output_directory(self) -> str:
        """Return the directory for artifacts, creating it when needed."""
        directory = self.output_directory or os.path.join(
            tempfile.gettempdir(), "satquery_outputs"
        )
        os.makedirs(directory, exist_ok=True)
        return directory


class ToolOutput(BaseModel):
    """The structured result of one tool execution."""

    tool_id: str
    result_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    statistics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None


class RemoteSensingTool(ABC):
    """Base class for a registered tool's actual implementation."""

    #: Must match the ``tool_id`` of the corresponding Registry entry.
    tool_id: str = ""

    #: Result type reported back to Result Integration.
    result_type: str = "generic"

    @abstractmethod
    def execute(self, request: ToolRequest) -> ToolOutput:
        """Run the tool and return its structured output."""

    # -- helpers shared by implementations ---------------------------
    def require_single_input(self, request: ToolRequest) -> str:
        """Return the one input reference this tool needs."""
        if not request.input_references:
            raise ToolExecutionError(
                f"Tool '{self.tool_id}' requires one input raster but none was supplied."
            )
        if len(request.input_references) > 1:
            raise ToolExecutionError(
                f"Tool '{self.tool_id}' accepts a single input raster but "
                f"{len(request.input_references)} were supplied."
            )
        return request.input_references[0]
