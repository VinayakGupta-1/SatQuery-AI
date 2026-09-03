from typing import List

from pydantic import BaseModel, Field

from app.controller.planning.planner import TaskPlan
from app.controller.task_classification.task_classification import TaskClassificationResult
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult


class InputRequirements(BaseModel):
    task_category: str
    required_inputs: List[str] = Field(default_factory=list)
    minimum_image_count: int = 0
    required_modalities: List[str] = Field(default_factory=list)
    required_bands: List[str] = Field(default_factory=list)
    requires_metadata: bool = False
    requires_crs: bool = False
    requires_temporal_information: bool = False
    compatibility_requirements: List[str] = Field(default_factory=list)


class InputRequirementsResolver:
    """Determines requirements for a planned remote-sensing task."""

    def resolve(self, understanding: TaskUnderstandingResult, classification: TaskClassificationResult, plan: TaskPlan) -> InputRequirements:
        if not isinstance(understanding, TaskUnderstandingResult):
            raise TypeError("understanding must be a TaskUnderstandingResult")
        if not isinstance(classification, TaskClassificationResult):
            raise TypeError("classification must be a TaskClassificationResult")
        if not isinstance(plan, TaskPlan):
            raise TypeError("plan must be a TaskPlan")

        category = classification.task_category
        if category == "change_detection":
            return self._change_detection_requirements()
        if category == "index_analysis":
            return self._index_analysis_requirements(understanding)
        if category == "object_detection":
            return self._object_detection_requirements()
        if category == "segmentation":
            return self._segmentation_requirements()
        if category == "scene_classification":
            return self._scene_classification_requirements()
        if category == "image_analysis":
            return self._image_analysis_requirements()
        return self._unknown_requirements()

    def _change_detection_requirements(self) -> InputRequirements:
        return InputRequirements(task_category="change_detection", required_inputs=["image_1", "image_2"], minimum_image_count=2, required_modalities=["compatible_modality"], requires_metadata=True, requires_crs=True, requires_temporal_information=True, compatibility_requirements=["spatial reference systems must be compatible", "spatial coverage must be compatible", "temporal ordering must be valid", "image modalities must be compatible"])

    def _index_analysis_requirements(self, understanding: TaskUnderstandingResult) -> InputRequirements:
        bands = {
            "ndvi": ["red", "nir"],
            "ndwi": ["green", "nir"],
            "ndbi": ["nir", "swir"],
        }.get(understanding.task_type, ["required_spectral_bands"])
        return InputRequirements(task_category="index_analysis", required_inputs=["satellite_image"], minimum_image_count=1, required_modalities=["optical"], required_bands=bands, requires_metadata=True, requires_crs=True, compatibility_requirements=["required spectral bands must be available"])

    def _object_detection_requirements(self) -> InputRequirements:
        return self._single_image_requirements("object_detection", "image resolution must be compatible with detection capability")

    def _segmentation_requirements(self) -> InputRequirements:
        return self._single_image_requirements("segmentation", "image must be compatible with segmentation capability")

    def _scene_classification_requirements(self) -> InputRequirements:
        return self._single_image_requirements("scene_classification", "image must be compatible with scene classification capability")

    @staticmethod
    def _single_image_requirements(category: str, compatibility: str) -> InputRequirements:
        return InputRequirements(task_category=category, required_inputs=["satellite_image"], minimum_image_count=1, required_modalities=["compatible_imagery"], requires_metadata=True, requires_crs=True, compatibility_requirements=[compatibility])

    @staticmethod
    def _image_analysis_requirements() -> InputRequirements:
        return InputRequirements(task_category="image_analysis", required_inputs=["satellite_image"], minimum_image_count=1, required_modalities=["compatible_imagery"], requires_metadata=True, requires_crs=True)

    @staticmethod
    def _unknown_requirements() -> InputRequirements:
        return InputRequirements(task_category="unknown")
