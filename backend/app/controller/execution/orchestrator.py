from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.registry.registry import get_tool
from app.tools.base import ToolExecutionError, ToolOutput
from app.tools.binding import has_implementation, implemented_tool_ids
from app.tools.executor import ToolExecutor, ToolNotImplementedError


class ExecutionRequest(BaseModel):
    tool_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    input_references: List[str] = Field(default_factory=list)
    output_directory: Optional[str] = None


class ExecutionResult(BaseModel):
    tool_id: str
    status: str = "ready"
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionOrchestrator:
    """Coordinates execution of a registered tool.

    The orchestrator enforces the Registry contract -- existence, enablement,
    inputs, image counts and parameter legality -- and then hands the request
    to the bound implementation. It never decides *which* tool to use; that
    happened in tool selection, and it never computes anything itself.
    """

    def __init__(self, executor: Optional[ToolExecutor] = None) -> None:
        self.executor = executor or ToolExecutor()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if not isinstance(request, ExecutionRequest):
            raise TypeError("request must be an ExecutionRequest")

        tool = get_tool(request.tool_id)
        if tool is None:
            return ExecutionResult(tool_id=request.tool_id, status="failed", error="Requested tool does not exist in the registry.")
        if not tool.enabled:
            return ExecutionResult(tool_id=tool.tool_id, status="blocked", error="Requested tool is disabled.")
        if not request.input_references:
            return ExecutionResult(tool_id=tool.tool_id, status="blocked", error="At least one input reference is required.")

        image_count = len(request.input_references)
        if image_count < tool.min_images or image_count > tool.max_images:
            return ExecutionResult(
                tool_id=tool.tool_id,
                status="blocked",
                error=(
                    f"Tool '{tool.tool_id}' accepts between {tool.min_images} and "
                    f"{tool.max_images} input(s), but {image_count} were supplied."
                ),
            )

        missing_parameters = self._find_missing_parameters(tool, request.parameters)
        if missing_parameters:
            return ExecutionResult(tool_id=tool.tool_id, status="blocked", error="Missing required parameters: " + ", ".join(missing_parameters))

        unknown_parameters = self._find_unknown_parameters(tool, request.parameters)
        if unknown_parameters:
            return ExecutionResult(tool_id=tool.tool_id, status="failed", error="Unknown parameters: " + ", ".join(unknown_parameters))

        if not has_implementation(tool.tool_id):
            return ExecutionResult(
                tool_id=tool.tool_id,
                status="blocked",
                error=(
                    f"Tool '{tool.tool_id}' is registered but no execution "
                    "implementation is bound to it yet. Implemented tools: "
                    f"{implemented_tool_ids()}."
                ),
                execution_metadata=self._metadata(tool, request),
            )

        metadata = self._metadata(tool, request)
        try:
            output = self._execute_registered_tool(
                tool.tool_id,
                request.parameters,
                request.input_references,
                request.output_directory,
            )
        except ToolNotImplementedError as exc:
            return ExecutionResult(tool_id=tool.tool_id, status="blocked", error=str(exc), execution_metadata=metadata)
        except Exception as exc:
            return ExecutionResult(tool_id=tool.tool_id, status="failed", error=str(exc), execution_metadata=metadata)

        if isinstance(output, ToolOutput):
            metadata.update(output.metadata)
            metadata["result_type"] = output.result_type
            metadata["artifacts"] = [artifact.path for artifact in output.artifacts]
            output = output.model_dump()

        return ExecutionResult(tool_id=tool.tool_id, status="completed", output=output, execution_metadata=metadata)

    @staticmethod
    def _metadata(tool: Any, request: ExecutionRequest) -> Dict[str, Any]:
        return {
            "tool_name": tool.name,
            "tool_type": tool.tool_type.value,
            "input_count": len(request.input_references),
        }

    @staticmethod
    def _find_missing_parameters(tool: Any, parameters: Dict[str, Any]) -> List[str]:
        return [name for name, parameter_type in tool.parameters.items() if parameter_type.startswith("required:") and name not in parameters]

    @staticmethod
    def _find_unknown_parameters(tool: Any, parameters: Dict[str, Any]) -> List[str]:
        if not tool.parameters:
            return list(parameters.keys())
        return [name for name in parameters if name not in tool.parameters]

    def _execute_registered_tool(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        input_references: List[str],
        output_directory: Optional[str] = None,
    ) -> ToolOutput:
        """Run the real implementation bound to ``tool_id``.

        This is the single boundary between the controller and actual
        remote-sensing computation. Overriding it in a test replaces the tool
        layer without touching any Registry policy above it.
        """
        return self.executor.run(
            tool_id=tool_id,
            parameters=parameters,
            input_references=input_references,
            output_directory=output_directory,
        )


__all__ = [
    "ExecutionOrchestrator",
    "ExecutionRequest",
    "ExecutionResult",
    "ToolExecutionError",
]
