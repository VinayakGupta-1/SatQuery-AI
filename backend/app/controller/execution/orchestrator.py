from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.registry.registry import get_tool


class ExecutionRequest(BaseModel):
    tool_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    input_references: List[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    tool_id: str
    status: str = "ready"
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionOrchestrator:
    """Coordinates execution of a registered tool."""

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

        missing_parameters = self._find_missing_parameters(tool, request.parameters)
        if missing_parameters:
            return ExecutionResult(tool_id=tool.tool_id, status="blocked", error="Missing required parameters: " + ", ".join(missing_parameters))

        unknown_parameters = self._find_unknown_parameters(tool, request.parameters)
        if unknown_parameters:
            return ExecutionResult(tool_id=tool.tool_id, status="failed", error="Unknown parameters: " + ", ".join(unknown_parameters))

        metadata = {"tool_name": tool.name, "tool_type": tool.tool_type.value, "input_count": len(request.input_references)}
        try:
            output = self._execute_registered_tool(tool.tool_id, request.parameters, request.input_references)
            return ExecutionResult(tool_id=tool.tool_id, status="completed", output=output, execution_metadata=metadata)
        except Exception as exc:
            return ExecutionResult(tool_id=tool.tool_id, status="failed", error=str(exc), execution_metadata=metadata)

    @staticmethod
    def _find_missing_parameters(tool: Any, parameters: Dict[str, Any]) -> List[str]:
        return [name for name, parameter_type in tool.parameters.items() if parameter_type.startswith("required:") and name not in parameters]

    @staticmethod
    def _find_unknown_parameters(tool: Any, parameters: Dict[str, Any]) -> List[str]:
        if not tool.parameters:
            return list(parameters.keys())
        return [name for name in parameters if name not in tool.parameters]

    @staticmethod
    def _execute_registered_tool(tool_id: str, parameters: Dict[str, Any], input_references: List[str]) -> Dict[str, Any]:
        """Return the deterministic execution adapter response."""
        return {"tool_id": tool_id, "parameters": parameters, "input_references": input_references}
