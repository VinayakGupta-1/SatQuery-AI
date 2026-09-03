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


class ToolDefinition(BaseModel):
    tool_id: str
    name: str
    description: str
    tool_type: ToolType
    supported_modalities: list[str] = Field(default_factory=list)
    required_bands: list[str] = Field(default_factory=list)
    min_images: int = 1
    max_images: int = 1
    requires_temporal_pair: bool = False
    parameters: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


# ============================================================
# REGISTERED TOOLS
# ============================================================
TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        tool_id="ndvi", name="NDVI",
        description="Computes Normalized Difference Vegetation Index from optical satellite imagery.",
        tool_type=ToolType.INDEX, supported_modalities=["optical"],
        required_bands=["red", "nir"], min_images=1, max_images=1,
        parameters={
            "red_band": "str",
            "nir_band": "str",
        },
    ),
    ToolDefinition(
        tool_id="ndwi", name="NDWI",
        description="Computes Normalized Difference Water Index from optical satellite imagery.",
        tool_type=ToolType.INDEX, supported_modalities=["optical"],
        required_bands=["green", "nir"], min_images=1, max_images=1,
    ),
    ToolDefinition(
        tool_id="ndbi", name="NDBI",
        description="Computes Normalized Difference Built-up Index from optical satellite imagery.",
        tool_type=ToolType.INDEX, supported_modalities=["optical"],
        required_bands=["nir", "swir"], min_images=1, max_images=1,
    ),
    ToolDefinition(
        tool_id="satellite_vqa", name="Satellite Visual Question Answering",
        description="Answers natural-language questions about satellite imagery.",
        tool_type=ToolType.VQA, supported_modalities=["optical", "sar"],
        min_images=1, max_images=1,
    ),
    ToolDefinition(
        tool_id="land_cover_classification", name="Land Cover Classification",
        description="Classifies satellite imagery into land-cover categories.",
        tool_type=ToolType.CLASSIFICATION, supported_modalities=["optical"],
        min_images=1, max_images=1,
    ),
    ToolDefinition(
        tool_id="object_detection", name="Satellite Object Detection",
        description="Detects objects of interest in satellite imagery.",
        tool_type=ToolType.OBJECT_DETECTION, supported_modalities=["optical"],
        min_images=1, max_images=1,
    ),
    ToolDefinition(
        tool_id="change_detection", name="Bi-Temporal Change Detection",
        description="Detects changes between two satellite images acquired at different times.",
        tool_type=ToolType.CHANGE_DETECTION,
        supported_modalities=["optical", "sar"], min_images=2, max_images=2,
        requires_temporal_pair=True,
    ),
    ToolDefinition(
        tool_id="sar_analysis", name="SAR Analysis",
        description="Performs analysis on Synthetic Aperture Radar satellite imagery.",
        tool_type=ToolType.SAR_ANALYSIS, supported_modalities=["sar"],
        min_images=1, max_images=1,
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


def get_enabled_tools() -> list[ToolDefinition]:
    """Return only tools currently enabled."""
    return [tool for tool in TOOLS if tool.enabled]
