"""Bridge between the controller's requirements and the validator's.

Two ``InputRequirements`` models exist in this project, for good reasons:

* :class:`app.controller.input_requirements.input_requirements.InputRequirements`
  is what the controller *reasons* about. It is task-shaped, carries the task
  category, and uses descriptive phrases such as ``"compatible_imagery"``.
* :class:`app.schemas.task.InputRequirements` is what the deterministic
  validator *enforces*. It is check-shaped: every field maps to one concrete
  test the validator performs.

Nothing connected them, so the validator could not actually be run on what the
controller produced. This module performs that translation, which keeps both
models intact and puts the validator back into the pipeline as step 5.

The translation is deliberately conservative: a requirement the controller did
not express is never invented here, and descriptive placeholders are dropped
rather than being enforced as literal band or modality names.
"""

from __future__ import annotations

from app.controller.input_requirements.input_requirements import InputRequirements
from app.registry.registry import ToolDefinition
from app.schemas.task import InputRequirements as ValidationRequirements

#: Controller phrases that mean "any modality is acceptable" rather than naming
#: a modality the validator should match against image metadata.
MODALITY_PLACEHOLDERS = {"compatible_imagery", "compatible_modality"}

#: Controller phrase meaning "this task needs bands, but which ones depends on
#: the specific index" -- not a band name to look for in the imagery.
BAND_PLACEHOLDERS = {"required_spectral_bands"}

#: Compatibility phrase that maps onto a concrete validator check.
SAME_AREA_PHRASE = "spatial coverage must be compatible"


def to_validation_requirements(
    requirements: InputRequirements,
    tool: ToolDefinition | None = None,
) -> ValidationRequirements:
    """Translate controller requirements into validator requirements.

    ``tool`` is the tool chosen by tool selection. When supplied, the Registry
    definition provides the upper bound on image count and the authoritative
    temporal-pair requirement, so the validator enforces exactly what the
    selected tool can actually accept.
    """
    if not isinstance(requirements, InputRequirements):
        raise TypeError("requirements must be an InputRequirements")

    modalities = [
        modality
        for modality in requirements.required_modalities
        if modality not in MODALITY_PLACEHOLDERS
    ]
    bands = [
        band for band in requirements.required_bands if band not in BAND_PLACEHOLDERS
    ]

    if tool is not None:
        maximum = tool.max_images
        temporal_pair = tool.requires_temporal_pair
    else:
        # A max of 0 means "no upper bound" to the validator.
        maximum = 0
        temporal_pair = requirements.task_category == "change_detection"

    return ValidationRequirements(
        min_images=requirements.minimum_image_count,
        max_images=maximum,
        required_modalities=modalities,
        required_bands=bands,
        requires_metadata=requirements.requires_metadata,
        requires_crs=requirements.requires_crs,
        requires_georeferencing=requirements.requires_crs,
        requires_temporal_information=requirements.requires_temporal_information,
        requires_same_area=SAME_AREA_PHRASE in requirements.compatibility_requirements,
        requires_temporal_pair=temporal_pair,
        requires_optical_input=modalities == ["optical"],
        requires_sar_input=modalities == ["sar"],
    )
