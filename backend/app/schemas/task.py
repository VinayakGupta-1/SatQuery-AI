from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    SINGLE_IMAGE_VQA = "single_image_vqa"
    IMAGE_CAPTIONING = "image_captioning"
    BI_TEMPORAL_CHANGE_ANALYSIS = "bi_temporal_change_analysis"
    OPTICAL_SAR_ANALYSIS = "optical_sar_analysis"
    UNKNOWN = "unknown"


class TaskStatus(str, Enum):
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    VALIDATING = "validating"
    INPUT_REQUIRED = "input_required"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NextAction(str, Enum):
    REQUEST_INPUT = "request_input"
    VALIDATE_INPUT = "validate_input"
    SELECT_TOOL = "select_tool"
    EXECUTE = "execute"
    INSPECT_RESULT = "inspect_result"
    COMPLETE = "complete"


class InputReference(BaseModel):
    id: str
    type: str = "image"
    path: str | None = None


class InputRequirements(BaseModel):
    min_images: int = 0
    max_images: int = 0

    required_modalities: list[str] = Field(default_factory=list)
    required_bands: list[str] = Field(default_factory=list)

    requires_metadata: bool = False
    requires_georeferencing: bool = False
    requires_crs: bool = False

    requires_temporal_information: bool = False
    requires_same_area: bool = False
    requires_temporal_pair: bool = False

    requires_optical_input: bool = False
    requires_sar_input: bool = False


class TaskParameters(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class ExecutionStep(BaseModel):
    step_id: str
    tool_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"


class SatQueryTask(BaseModel):
    task_id: str
    query: str

    task_type: TaskType = TaskType.UNKNOWN
    intent: str | None = None

    inputs: list[InputReference] = Field(default_factory=list)

    requirements: InputRequirements | None = None

    parameters: TaskParameters = Field(
        default_factory=TaskParameters
    )

    selected_tools: list[str] = Field(default_factory=list)

    execution_plan: list[ExecutionStep] = Field(
        default_factory=list
    )

    status: TaskStatus = TaskStatus.RECEIVED

    next_action: NextAction | None = None

    confidence: float | None = None