from typing import List

from pydantic import BaseModel, Field

from app.controller.task_classification import TaskClassificationResult
from app.controller.task_understanding import TaskUnderstandingResult


class PlanStep(BaseModel):
    """A single step in the execution plan."""
    step_id: int
    action: str
    description: str


class TaskPlan(BaseModel):
    """Deterministic execution plan for a SatQuery task."""
    task_category: str
    steps: List[PlanStep] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    status: str = "planned"


class Planner:
    """Creates a deterministic plan from task understanding and classification."""

    def create_plan(
        self,
        understanding: TaskUnderstandingResult,
        classification: TaskClassificationResult,
    ) -> TaskPlan:
        if not isinstance(understanding, TaskUnderstandingResult):
            raise TypeError("understanding must be a TaskUnderstandingResult")
        if not isinstance(classification, TaskClassificationResult):
            raise TypeError("classification must be a TaskClassificationResult")

        category = classification.task_category
        if category == "change_detection":
            return self._change_detection_plan()
        if category == "index_analysis":
            return self._index_analysis_plan(understanding)
        if category == "object_detection":
            return self._object_detection_plan()
        if category == "segmentation":
            return self._segmentation_plan()
        if category == "scene_classification":
            return self._scene_classification_plan()
        if category == "image_analysis":
            return self._image_analysis_plan()
        return self._unknown_plan()

    @staticmethod
    def _make_plan(
        category: str, actions: list[str], capabilities: list[str],
    ) -> TaskPlan:
        steps = [
            PlanStep(step_id=index, action=action, description=action.replace("_", " ").capitalize() + ".")
            for index, action in enumerate(actions, start=1)
        ]
        return TaskPlan(
            task_category=category,
            steps=steps,
            required_capabilities=capabilities,
        )

    @staticmethod
    def _change_detection_plan() -> TaskPlan:
        return Planner._make_plan(
            "change_detection",
            ["validate_inputs", "check_temporal_compatibility", "check_spatial_compatibility", "prepare_image_pair", "run_change_detection", "generate_result"],
            ["image_validation", "temporal_analysis", "spatial_compatibility", "change_detection"],
        )

    @staticmethod
    def _index_analysis_plan(understanding: TaskUnderstandingResult) -> TaskPlan:
        return Planner._make_plan(
            "index_analysis",
            ["validate_inputs", "check_required_bands", "prepare_bands", "calculate_index", "generate_result"],
            ["image_validation", "spectral_band_analysis", "index_computation"],
        )

    @staticmethod
    def _object_detection_plan() -> TaskPlan:
        return Planner._make_plan(
            "object_detection",
            ["validate_inputs", "check_image_compatibility", "prepare_image", "run_object_detection", "generate_result"],
            ["image_validation", "object_detection"],
        )

    @staticmethod
    def _segmentation_plan() -> TaskPlan:
        return Planner._make_plan(
            "segmentation",
            ["validate_inputs", "check_image_compatibility", "prepare_image", "run_segmentation", "generate_result"],
            ["image_validation", "segmentation"],
        )

    @staticmethod
    def _scene_classification_plan() -> TaskPlan:
        return Planner._make_plan(
            "scene_classification",
            ["validate_inputs", "check_image_compatibility", "prepare_image", "run_classification", "generate_result"],
            ["image_validation", "scene_classification"],
        )

    @staticmethod
    def _image_analysis_plan() -> TaskPlan:
        return Planner._make_plan(
            "image_analysis",
            ["validate_inputs", "prepare_image", "analyze_image", "generate_result"],
            ["image_validation", "image_analysis"],
        )

    @staticmethod
    def _unknown_plan() -> TaskPlan:
        return TaskPlan(
            task_category="unknown",
            steps=[],
            required_capabilities=[],
            status="requires_clarification",
        )
