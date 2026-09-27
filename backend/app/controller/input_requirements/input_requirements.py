from typing import List, Optional

from pydantic import BaseModel, Field

from app.controller.planning.planner import TaskPlan
from app.controller.task_classification.task_classification import TaskClassificationResult
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult
from app.schemas.spatiotemporal import AreaOfInterest, TimeRange


#: The bands each spectral index needs, in logical names.
INDEX_BANDS = {
    "ndvi": ["red", "nir"],
    "ndwi": ["green", "nir"],
    "ndbi": ["nir", "swir"],
}

#: What a change request is about decides which index is differenced: a
#: question about water compared by NDVI would report vegetation change and
#: call it an answer. Checked in order; vegetation is the default.
CHANGE_SUBJECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ndwi", ("water", "flood", "inundat", "reservoir", "lake", "river", "wetland", "pond")),
    ("ndbi", ("built-up", "built up", "urban", "construction", "settlement", "building", "impervious")),
    ("ndvi", ("vegetation", "forest", "deforest", "crop", "tree", "green", "agricultur", "farm")),
)

#: How far apart an optical and a SAR image may be acquired and still be fused.
#: Sentinel-1 revisits every 6-12 days; beyond that a flood can come and go
#: between the two images, and "fusion" would describe two different events.
FUSION_MAX_DAYS = 12


def change_index_for(understanding: TaskUnderstandingResult) -> str:
    """Return the index a change-detection request should difference."""
    query = understanding.original_query.lower()
    for index, words in CHANGE_SUBJECTS:
        if any(word in query for word in words):
            return index
    return "ndvi"


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
    #: Exactly one optical image and one SAR image.
    requires_optical_and_sar_pair: bool = False
    #: The images must be acquired within this many days of each other.
    max_days_between_images: Optional[int] = None
    #: The period the question names; every acquisition date must fall in it.
    time_range: Optional[TimeRange] = None
    #: The area the question names; it must overlap the imagery.
    aoi: Optional[AreaOfInterest] = None


class InputRequirementsResolver:
    """Determines requirements for a planned remote-sensing task."""

    def resolve(self, understanding: TaskUnderstandingResult, classification: TaskClassificationResult, plan: TaskPlan) -> InputRequirements:
        if not isinstance(understanding, TaskUnderstandingResult):
            raise TypeError("understanding must be a TaskUnderstandingResult")
        if not isinstance(classification, TaskClassificationResult):
            raise TypeError("classification must be a TaskClassificationResult")
        if not isinstance(plan, TaskPlan):
            raise TypeError("plan must be a TaskPlan")

        requirements = self._for_category(classification.task_category, understanding)
        # Where and when the question is about constrain the imagery whatever
        # the task: a question about 2024 cannot be answered from a 2019 scene.
        if requirements.task_category != "unknown":
            requirements.time_range = understanding.context.time_range
            requirements.aoi = understanding.context.aoi
        return requirements

    def _for_category(self, category: str, understanding: TaskUnderstandingResult) -> InputRequirements:
        if category == "change_detection":
            return self._change_detection_requirements(understanding)
        if category == "index_analysis":
            return self._index_analysis_requirements(understanding)
        if category == "object_detection":
            return self._object_detection_requirements()
        if category == "segmentation":
            return self._segmentation_requirements()
        if category == "scene_classification":
            return self._scene_classification_requirements()
        if category == "image_analysis":
            return self._vision_requirements("image_analysis")
        if category == "image_captioning":
            return self._vision_requirements("image_captioning")
        if category == "sar_analysis":
            return self._sar_analysis_requirements()
        if category == "optical_sar_fusion":
            return self._fusion_requirements()
        if category == "change_vqa":
            requirements = self._change_detection_requirements(understanding)
            requirements.task_category = "change_vqa"
            return requirements
        return self._unknown_requirements()

    def _change_detection_requirements(self, understanding: TaskUnderstandingResult) -> InputRequirements:
        # A radar pair is compared by backscatter and needs no optical band;
        # an optical pair needs the bands of the index that will be differenced.
        if understanding.imagery_modality == "sar":
            modalities, bands = ["sar"], []
        else:
            modalities, bands = ["compatible_modality"], INDEX_BANDS[change_index_for(understanding)]
        return InputRequirements(task_category="change_detection", required_inputs=["image_1", "image_2"], minimum_image_count=2, required_modalities=modalities, required_bands=bands, requires_metadata=True, requires_crs=True, requires_temporal_information=True, compatibility_requirements=["spatial reference systems must be compatible", "spatial coverage must be compatible", "temporal ordering must be valid", "image modalities must be compatible"])

    def _index_analysis_requirements(self, understanding: TaskUnderstandingResult) -> InputRequirements:
        task = "ndwi" if understanding.task_type == "flood_mapping" else understanding.task_type
        bands = INDEX_BANDS.get(task, ["required_spectral_bands"])
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
    def _vision_requirements(category: str) -> InputRequirements:
        # A vision model reads pixels, not coordinates, so georeferencing is
        # not required -- when present it lets answers be placed on the ground.
        return InputRequirements(task_category=category, required_inputs=["satellite_image"], minimum_image_count=1, required_modalities=["compatible_imagery"], requires_metadata=True, requires_crs=False)

    @staticmethod
    def _sar_analysis_requirements() -> InputRequirements:
        return InputRequirements(task_category="sar_analysis", required_inputs=["sar_image"], minimum_image_count=1, required_modalities=["sar"], requires_metadata=True, requires_crs=True, compatibility_requirements=["image must be calibrated SAR backscatter"])

    @staticmethod
    def _fusion_requirements() -> InputRequirements:
        return InputRequirements(
            task_category="optical_sar_fusion",
            required_inputs=["optical_image", "sar_image"],
            minimum_image_count=2,
            required_modalities=["optical", "sar"],
            requires_metadata=True,
            requires_crs=True,
            requires_temporal_information=True,
            requires_optical_and_sar_pair=True,
            max_days_between_images=FUSION_MAX_DAYS,
            compatibility_requirements=[
                "one optical and one SAR image",
                "spatial coverage must be compatible",
                f"acquired within {FUSION_MAX_DAYS} days of each other",
            ],
        )

    @staticmethod
    def _unknown_requirements() -> InputRequirements:
        return InputRequirements(task_category="unknown")
