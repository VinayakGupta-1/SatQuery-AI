from enum import Enum

from pydantic import BaseModel, Field


class ToolType(str, Enum):
    INDEX = "index"
    VQA = "vqa"
    SEGMENTATION = "segmentation"
    OBJECT_DETECTION = "object_detection"
    CHANGE_DETECTION = "change_detection"
    CLASSIFICATION = "classification"
    SAR_ANALYSIS = "sar_analysis"
    FUSION = "fusion"
    CAPTIONING = "captioning"


class Engine(str, Enum):
    """Which side of the hybrid core answers: computed, or read by a model."""

    #: Exact arithmetic over the pixels. Reproducible to the bit.
    DETERMINISTIC = "deterministic"
    #: A vision-language model reads a rendering of the scene.
    VLM = "vlm"
    #: Measured first by a deterministic engine, then described by the model
    #: with those measurements in hand.
    HYBRID = "hybrid"


class OutputType(str, Enum):
    """What a tool hands back, so a frontend knows how to render it."""

    RASTER_INDEX = "raster_index"
    CHANGE_MAP = "change_map"
    CLASSES = "classes"
    DETECTIONS = "detections"
    MASK = "mask"
    TEXT = "text"


class ToolDefinition(BaseModel):
    tool_id: str
    name: str
    description: str
    tool_type: ToolType
    #: Semantic version of this capability's contract. It changes when the
    #: inputs, parameters or output shape change, so a stored result can always
    #: be traced to the contract that produced it.
    version: str = "1.0.0"
    #: The shape of the result, for the frontend.
    output_type: OutputType = OutputType.RASTER_INDEX
    supported_modalities: list[str] = Field(default_factory=list)
    required_bands: list[str] = Field(default_factory=list)
    min_images: int = 1
    max_images: int = 1
    requires_temporal_pair: bool = False
    parameters: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    #: Where the orchestrator routes this capability: the deterministic
    #: engines, the vision-language model, or both in sequence.
    engine: Engine = Engine.DETERMINISTIC


# An area of interest, which every tool clips its input to before computing.
# ``aoi_bbox`` is [min_x, min_y, max_x, max_y] in ``aoi_crs`` (longitude and
# latitude by default); ``aoi_region`` names a part of the scene instead.
AOI_PARAMETERS: dict[str, str] = {
    "aoi_bbox": "list",
    "aoi_crs": "str",
    "aoi_region": "str",
}

# Parameters every normalised-difference index tool accepts. ``scale`` and
# ``offset`` convert digital numbers to reflectance: a normalised difference is
# invariant under a shared scale but *not* under an additive offset, so
# Sentinel-2 baseline 04.00 products must pass their BOA_ADD_OFFSET here.
INDEX_COMMON_PARAMETERS: dict[str, str] = {
    "scale": "float",
    "offset": "float",
    "sensor": "str",
    "write_raster": "bool",
    # Cloud/QA masking. Naming a mask band (Sentinel-2 "SCL", Landsat
    # "QA_PIXEL") excludes cloud, shadow and defective pixels, without which
    # an index averaged over a cloudy scene is confidently wrong.
    "mask_band": "str",
    "mask_invalid_values": "str",
    **AOI_PARAMETERS,
}

# Backscatter handling shared by every tool that reads SAR.
SAR_PARAMETERS: dict[str, str] = {
    "polarisation": "str",
    "input_units": "str",
    "threshold_db": "float",
    "threshold_method": "str",
    "speckle_filter": "str",
    "filter_window": "int",
}

# Bands and rule thresholds of the land-cover classifier, shared by region
# detection, which extracts objects from the same classification.
LAND_COVER_PARAMETERS: dict[str, str] = {
    "green_band": "str",
    "red_band": "str",
    "nir_band": "str",
    "swir_band": "str",
    "water_threshold": "float",
    "vegetation_threshold": "float",
    "dense_vegetation_threshold": "float",
    "built_up_threshold": "float",
}


# ============================================================
# REGISTERED TOOLS
# ============================================================
TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        tool_id="ndvi", name="NDVI", version="1.0.0",
        output_type=OutputType.RASTER_INDEX,
        description="Computes Normalized Difference Vegetation Index from optical satellite imagery.",
        tool_type=ToolType.INDEX, supported_modalities=["optical"],
        required_bands=["red", "nir"], min_images=1, max_images=1,
        parameters={
            "red_band": "str",
            "nir_band": "str",
            **INDEX_COMMON_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="ndwi", name="NDWI", version="1.0.0",
        output_type=OutputType.RASTER_INDEX,
        description="Computes Normalized Difference Water Index from optical satellite imagery.",
        tool_type=ToolType.INDEX, supported_modalities=["optical"],
        required_bands=["green", "nir"], min_images=1, max_images=1,
        parameters={
            "green_band": "str",
            "nir_band": "str",
            **INDEX_COMMON_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="ndbi", name="NDBI", version="1.0.0",
        output_type=OutputType.RASTER_INDEX,
        description="Computes Normalized Difference Built-up Index from optical satellite imagery.",
        tool_type=ToolType.INDEX, supported_modalities=["optical"],
        required_bands=["nir", "swir"], min_images=1, max_images=1,
        parameters={
            "nir_band": "str",
            "swir_band": "str",
            **INDEX_COMMON_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="satellite_vqa", name="Satellite Visual Question Answering",
        version="1.1.0", output_type=OutputType.TEXT, engine=Engine.VLM,
        description=(
            "Answers free-form questions about a scene -- or about an optical and a "
            "radar image of it together -- with the vision-language model. Off "
            "unless an operator enables it."
        ),
        tool_type=ToolType.VQA, supported_modalities=["optical", "sar"],
        # Two images only as an optical + SAR pair, read together.
        min_images=1, max_images=2,
        parameters={
            # The user's own question, filled in by the parameter configurator.
            "question": "str",
            "write_raster": "bool",
            **AOI_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="image_captioning", name="Image Captioning and Region Grounding",
        version="1.0.0", output_type=OutputType.TEXT, engine=Engine.VLM,
        description=(
            "Describes a scene in a few sentences and outlines the regions the "
            "description refers to, placed back on the map. Off unless an operator "
            "enables the vision-language model."
        ),
        tool_type=ToolType.CAPTIONING, supported_modalities=["optical", "sar"],
        min_images=1, max_images=1,
        parameters={"write_raster": "bool", **AOI_PARAMETERS},
    ),
    ToolDefinition(
        tool_id="change_vqa", name="Bi-Temporal Change VQA",
        version="1.0.0", output_type=OutputType.TEXT, engine=Engine.HYBRID,
        description=(
            "Answers a question about what changed between two dates: change is "
            "measured deterministically first, then the vision-language model "
            "answers with both images and those measurements in hand."
        ),
        tool_type=ToolType.VQA, supported_modalities=["optical", "sar"],
        min_images=2, max_images=2, requires_temporal_pair=True,
        parameters={
            "question": "str",
            "index": "str",
            "threshold": "float",
            "write_raster": "bool",
            **AOI_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="optical_sar_fusion", name="Optical + SAR Water Fusion",
        version="1.0.0", output_type=OutputType.CLASSES,
        description=(
            "Fuses an optical and a SAR image of the same area and time into one "
            "water map: where both sensors agree, where only one sees water, and "
            "where radar sees water under cloud the optical image cannot."
        ),
        tool_type=ToolType.FUSION, supported_modalities=["optical", "sar"],
        required_bands=[],
        min_images=2, max_images=2,
        parameters={
            "green_band": "str",
            "nir_band": "str",
            # NDWI above this is optical water.
            "water_threshold": "float",
            # Acquisitions further apart than this describe different events.
            "max_days_apart": "int",
            **SAR_PARAMETERS,
            **INDEX_COMMON_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="land_cover_classification", name="Land Cover Classification",
        version="1.0.0", output_type=OutputType.CLASSES,
        description=(
            "Classifies every pixel of an optical scene into water, dense and sparse "
            "vegetation, built-up land and bare soil with transparent spectral-index rules."
        ),
        tool_type=ToolType.CLASSIFICATION, supported_modalities=["optical"],
        required_bands=["green", "red", "nir"],
        min_images=1, max_images=1,
        parameters={**LAND_COVER_PARAMETERS, **INDEX_COMMON_PARAMETERS},
    ),
    ToolDefinition(
        tool_id="object_detection", name="Landscape Object Detection",
        version="1.0.0", output_type=OutputType.DETECTIONS,
        description=(
            "Detects discrete landscape objects -- water bodies, vegetation patches, "
            "built-up clusters and bare-land patches -- as connected regions with "
            "areas, bounding boxes and centroids."
        ),
        tool_type=ToolType.OBJECT_DETECTION, supported_modalities=["optical"],
        required_bands=["green", "red", "nir"],
        min_images=1, max_images=1,
        parameters={
            # Resolved from the understood query by the parameter configurator.
            "target_objects": "list",
            "min_area_pixels": "int",
            "max_objects": "int",
            "connectivity": "int",
            **LAND_COVER_PARAMETERS,
            **INDEX_COMMON_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="change_detection", name="Bi-Temporal Change Detection",
        version="1.0.0", output_type=OutputType.CHANGE_MAP,
        description="Detects changes between two satellite images acquired at different times.",
        tool_type=ToolType.CHANGE_DETECTION,
        supported_modalities=["optical", "sar"], min_images=2, max_images=2,
        requires_temporal_pair=True,
        parameters={
            # Which spectral index is differenced between the two dates.
            "index": "str",
            # Band overrides for whichever index is chosen.
            "red_band": "str",
            "nir_band": "str",
            "green_band": "str",
            "swir_band": "str",
            # How large a difference has to be before it counts as change.
            "threshold": "float",
            "threshold_method": "str",
            "sigma_multiplier": "float",
            # A radar pair is compared by backscatter instead of an index.
            "polarisation": "str",
            "input_units": "str",
            "speckle_filter": "str",
            "filter_window": "int",
            **INDEX_COMMON_PARAMETERS,
        },
    ),
    ToolDefinition(
        tool_id="sar_analysis", name="SAR Water and Flood Mapping",
        version="1.0.0", output_type=OutputType.CLASSES,
        description=(
            "Maps open water and flooding in SAR imagery by thresholding calibrated "
            "backscatter in decibels. Works through cloud and at night."
        ),
        tool_type=ToolType.SAR_ANALYSIS, supported_modalities=["sar"],
        min_images=1, max_images=1,
        parameters={
            **SAR_PARAMETERS,
            "write_raster": "bool",
            **AOI_PARAMETERS,
        },
    ),
]


# ============================================================
# REGISTRY ACCESS FUNCTIONS
# ============================================================
def get_all_tools() -> list[ToolDefinition]:
    """Return all registered tools."""
    return TOOLS.copy()


def get_tool(tool_id: str) -> ToolDefinition | None:
    """Return a tool by its unique ID."""
    for tool in TOOLS:
        if tool.tool_id == tool_id:
            return tool
    return None


def get_tool_version(tool_id: str) -> str | None:
    """Return the contract version of ``tool_id``, or ``None`` if unknown."""
    tool = get_tool(tool_id)
    return tool.version if tool else None


def get_enabled_tools() -> list[ToolDefinition]:
    """Return only tools currently enabled."""
    return [tool for tool in TOOLS if tool.enabled]
