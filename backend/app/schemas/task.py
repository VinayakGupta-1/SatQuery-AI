from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.spatiotemporal import AreaOfInterest, TimeRange


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

    #: Exactly one optical and one SAR image, as fusion needs.
    requires_optical_and_sar_pair: bool = False
    #: The images must be acquired within this many days of each other.
    max_days_between_images: int | None = None
    #: The period the question names; acquisition dates must fall inside it.
    time_range: TimeRange | None = None
    #: Only the latest image must fall inside ``time_range``. A flood map
    #: compares the flood-period scene with a dry-season reference that by
    #: design predates the period asked about.
    period_applies_to_latest_only: bool = False
    #: The area the question names; it must overlap every image.
    aoi: AreaOfInterest | None = None


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