from typing import List

from pydantic import BaseModel, Field

from app.controller.task_classification import TaskClassificationResult
from app.controller.task_understanding import TaskUnderstandingResult


class PlanStep(BaseModel):
    """A single step in the execution plan."""
    step_id: int
    action: str
    description: str


#: Which engine answers each category: computed by the deterministic engines,
#: read by the vision-language model, or both in sequence -- measured first,
#: then described by the model with the measurements in hand.
CATEGORY_ROUTES = {
    "image_analysis": "vlm",
    "image_captioning": "vlm",
    "change_vqa": "hybrid",
}


class TaskPlan(BaseModel):
    """Deterministic execution plan for a SatQuery task."""
    task_category: str
    steps: List[PlanStep] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    status: str = "planned"
    #: ``deterministic``, ``vlm`` or ``hybrid``: where the orchestrator sends
    #: the request. ``none`` when nothing can be planned.
    route: str = "deterministic"


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
        if category == "sar_analysis":
            return self._sar_analysis_plan()
        if category == "optical_sar_fusion":
            return self._make_plan(
                "optical_sar_fusion",
                ["validate_inputs", "check_sensor_pair", "check_spatial_compatibility", "map_optical_water", "map_radar_water", "fuse_water_maps", "generate_result"],
                ["image_validation", "optical_analysis", "sar_analysis", "cross_modal_fusion"],
            )
        if category == "image_captioning":
            return self._make_plan(
                "image_captioning",
                ["validate_inputs", "render_preview", "caption_with_vision_model", "ground_regions", "generate_result"],
                ["image_validation", "vision_language_model", "image_captioning"],
            )
        if category == "change_vqa":
            return self._make_plan(
                "change_vqa",
                ["validate_inputs", "check_temporal_compatibility", "measure_change", "render_previews", "answer_with_vision_model", "generate_result"],
                ["image_validation", "change_detection", "vision_language_model"],
            )
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
            route=CATEGORY_ROUTES.get(category, "deterministic"),
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
    def _sar_analysis_plan() -> TaskPlan:
        return Planner._make_plan(
            "sar_analysis",
            ["validate_inputs", "select_polarisation", "convert_backscatter_to_decibels", "threshold_backscatter", "generate_result"],
            ["image_validation", "sar_analysis"],
        )

    @staticmethod
    def _unknown_plan() -> TaskPlan:
        return TaskPlan(
            task_category="unknown",
            steps=[],
            required_capabilities=[],
            status="requires_clarification",
            route="none",
        )
