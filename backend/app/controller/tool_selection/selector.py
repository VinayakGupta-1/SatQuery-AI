from typing import List, Optional

from pydantic import BaseModel, Field

from app.controller.input_requirements.input_requirements import InputRequirements
from app.controller.planning.planner import TaskPlan
from app.controller.task_classification.task_classification import TaskClassificationResult
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult
from app.registry.registry import ToolDefinition, ToolType, get_enabled_tools


class ToolCandidate(BaseModel):
    tool_id: str
    tool_name: str
    score: float = 0.0
    reasons: List[str] = Field(default_factory=list)


class ToolSelectionResult(BaseModel):
    task_category: str
    selected_tool_id: Optional[str] = None
    selected_tool_name: Optional[str] = None
    capability: Optional[str] = None
    selection_reason: str = ""
    confidence: float = 0.0
    alternatives: List[ToolCandidate] = Field(default_factory=list)
    status: str = "selected"


class ToolSelector:
    """Selects the most suitable registered tool for a planned task."""
    CATEGORY_TO_TOOL_TYPE = {
        "index_analysis": ToolType.INDEX,
        "object_detection": ToolType.OBJECT_DETECTION,
        "change_detection": ToolType.CHANGE_DETECTION,
        "segmentation": ToolType.SEGMENTATION,
        "scene_classification": ToolType.CLASSIFICATION,
        "image_analysis": ToolType.VQA,
    }

    def select(self, understanding: TaskUnderstandingResult, classification: TaskClassificationResult, plan: TaskPlan, requirements: InputRequirements) -> ToolSelectionResult:
        if not isinstance(understanding, TaskUnderstandingResult):
            raise TypeError("understanding must be a TaskUnderstandingResult")
        if not isinstance(classification, TaskClassificationResult):
            raise TypeError("classification must be a TaskClassificationResult")
        if not isinstance(plan, TaskPlan):
            raise TypeError("plan must be a TaskPlan")
        if not isinstance(requirements, InputRequirements):
            raise TypeError("requirements must be an InputRequirements")

        category = classification.task_category
        if category == "unknown":
            return ToolSelectionResult(task_category=category, capability=category, selection_reason="Task category is unknown.", confidence=0.0, status="requires_clarification")

        expected_tool_type = self.CATEGORY_TO_TOOL_TYPE.get(category)
        if expected_tool_type is None:
            return ToolSelectionResult(task_category=category, capability=category, selection_reason="No registry mapping exists for this task category.", confidence=0.0, status="no_compatible_tool")

        candidates = []
        for tool in get_enabled_tools():
            score, reasons = self._evaluate_tool(tool, expected_tool_type, requirements)
            if score > 0:
                candidates.append(ToolCandidate(tool_id=tool.tool_id, tool_name=tool.name, score=score, reasons=reasons))

        if not candidates:
            return ToolSelectionResult(task_category=category, capability=category, selection_reason="No enabled registered tool satisfies the task requirements.", confidence=0.0, status="no_compatible_tool")

        candidates.sort(key=lambda candidate: (candidate.score, candidate.tool_id), reverse=True)
        selected = candidates[0]
        return ToolSelectionResult(task_category=category, selected_tool_id=selected.tool_id, selected_tool_name=selected.tool_name, capability=category, selection_reason=(f"Selected registered tool '{selected.tool_name}' because it satisfies the required task capability and input requirements."), confidence=min(selected.score, 1.0), alternatives=candidates[1:], status="selected")

    def _evaluate_tool(self, tool: ToolDefinition, expected_tool_type: ToolType, requirements: InputRequirements) -> tuple[float, List[str]]:
        reasons = []
        score = 0.0
        if tool.tool_type != expected_tool_type:
            return 0.0, []
        score += 0.40
        reasons.append("tool capability matches task category")

        required_images = requirements.minimum_image_count
        if required_images < tool.min_images or required_images > tool.max_images:
            return 0.0, []
        score += 0.20
        reasons.append("image count is compatible")

        required_modalities = requirements.required_modalities
        if required_modalities:
            modality_match = (
                "compatible_imagery" in required_modalities
                or "compatible_modality" in required_modalities
                or any(modality in tool.supported_modalities for modality in required_modalities)
            )
            if not modality_match:
                return 0.0, []
            score += 0.15
            reasons.append("modality requirements are compatible")

        required_bands = requirements.required_bands
        if required_bands:
            band_match = (
                "required_spectral_bands" in required_bands
                or all(band in tool.required_bands for band in required_bands)
            )
            if not band_match:
                return 0.0, []
            score += 0.15
            reasons.append("required spectral bands are supported")

        if requirements.requires_temporal_information:
            if not tool.requires_temporal_pair:
                return 0.0, []
            score += 0.10
            reasons.append("temporal pair requirement is supported")

        return min(score, 1.0), reasons
