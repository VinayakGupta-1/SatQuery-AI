from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.controller.input_requirements.input_requirements import InputRequirements
from app.controller.planning.planner import TaskPlan
from app.controller.task_classification.task_classification import TaskClassificationResult
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult
from app.controller.tool_selection.selector import ToolSelectionResult
from app.registry.registry import ToolDefinition, get_tool


class ParameterConfiguration(BaseModel):
    tool_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    resolved_parameters: Dict[str, Any] = Field(default_factory=dict)
    missing_parameters: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "configured"


class ParameterConfigurator:
    """Resolves parameters required by a selected registered tool."""

    def configure(self, understanding: TaskUnderstandingResult, classification: TaskClassificationResult, plan: TaskPlan, requirements: InputRequirements, selection: ToolSelectionResult, user_parameters: Optional[Dict[str, Any]] = None) -> ParameterConfiguration:
        self._validate_inputs(understanding, classification, plan, requirements, selection)
        if selection.status != "selected":
            return ParameterConfiguration(tool_id=selection.selected_tool_id or "", status="needs_input", validation_errors=["A valid tool must be selected before parameter configuration."])

        tool = get_tool(selection.selected_tool_id)
        if tool is None:
            return ParameterConfiguration(tool_id=selection.selected_tool_id or "", status="invalid", validation_errors=["Selected tool does not exist in the registry."])
        if not tool.enabled:
            return ParameterConfiguration(tool_id=tool.tool_id, status="invalid", validation_errors=["Selected tool is disabled."])

        supplied = user_parameters or {}
        errors = self._validate_parameter_names(tool, supplied)
        if errors:
            return ParameterConfiguration(tool_id=tool.tool_id, parameters=supplied, validation_errors=errors, status="invalid")

        resolved = dict(supplied)
        self._resolve_task_parameters(tool, understanding, requirements, resolved)
        missing = self._find_missing_parameters(tool, resolved)
        if missing:
            return ParameterConfiguration(tool_id=tool.tool_id, parameters=supplied, resolved_parameters=resolved, missing_parameters=missing, status="needs_input")

        errors = self._validate_parameter_values(tool, resolved)
        if errors:
            return ParameterConfiguration(tool_id=tool.tool_id, parameters=supplied, resolved_parameters=resolved, validation_errors=errors, status="invalid")
        return ParameterConfiguration(tool_id=tool.tool_id, parameters=supplied, resolved_parameters=resolved, confidence=self._calculate_confidence(supplied, resolved), status="configured")

    @staticmethod
    def _validate_inputs(understanding: TaskUnderstandingResult, classification: TaskClassificationResult, plan: TaskPlan, requirements: InputRequirements, selection: ToolSelectionResult) -> None:
        if not isinstance(understanding, TaskUnderstandingResult):
            raise TypeError("understanding must be a TaskUnderstandingResult")
        if not isinstance(classification, TaskClassificationResult):
            raise TypeError("classification must be a TaskClassificationResult")
        if not isinstance(plan, TaskPlan):
            raise TypeError("plan must be a TaskPlan")
        if not isinstance(requirements, InputRequirements):
            raise TypeError("requirements must be an InputRequirements")
        if not isinstance(selection, ToolSelectionResult):
            raise TypeError("selection must be a ToolSelectionResult")

    @staticmethod
    def _validate_parameter_names(tool: ToolDefinition, supplied: Dict[str, Any]) -> List[str]:
        if not tool.parameters:
            return [f"Tool '{tool.tool_id}' does not define any configurable parameters."] if supplied else []
        allowed = set(tool.parameters)
        return [f"Unknown parameter: {name}" for name in supplied if name not in allowed]

    @staticmethod
    def _resolve_task_parameters(tool: ToolDefinition, understanding: TaskUnderstandingResult, requirements: InputRequirements, resolved: Dict[str, Any]) -> None:
        bands = requirements.required_bands
        if tool.tool_id == "ndvi":
            if bands:
                resolved.setdefault("red_band", bands[0])
            if len(bands) >= 2:
                resolved.setdefault("nir_band", bands[1])
        elif tool.tool_id == "ndwi":
            if bands:
                resolved.setdefault("green_band", bands[0])
            if len(bands) >= 2:
                resolved.setdefault("nir_band", bands[1])
        elif tool.tool_id == "ndbi":
            if bands:
                resolved.setdefault("nir_band", bands[0])
            if len(bands) >= 2:
                resolved.setdefault("swir_band", bands[1])
        elif tool.tool_id == "object_detection" and understanding.objects:
            resolved.setdefault("target_objects", understanding.objects)

    @staticmethod
    def _find_missing_parameters(tool: ToolDefinition, resolved: Dict[str, Any]) -> List[str]:
        return [name for name, parameter_type in tool.parameters.items() if parameter_type.startswith("required:") and name not in resolved]

    @staticmethod
    def _validate_parameter_values(tool: ToolDefinition, resolved: Dict[str, Any]) -> List[str]:
        errors = []
        types = {"float": (float, int), "int": (int,), "str": (str,), "bool": (bool,)}
        for name, value in resolved.items():
            if name not in tool.parameters:
                continue
            expected = tool.parameters[name].replace("required:", "")
            if expected in types and not isinstance(value, types[expected]):
                errors.append(f"Parameter '{name}' must be a {expected}.")
        return errors

    @staticmethod
    def _calculate_confidence(supplied: Dict[str, Any], resolved: Dict[str, Any]) -> float:
        if not resolved:
            return 0.0
        if not supplied:
            return 0.90
        return min(0.90 + 0.10 * len(supplied) / len(resolved), 1.0)
