from enum import Enum
from pydantic import BaseModel, Field

class ErrorCode(str, Enum):
    INVALID_FILE = "INVALID_FILE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    MISSING_INPUT = "MISSING_INPUT"
    INVALID_IMAGE_COUNT = "INVALID_IMAGE_COUNT"
    MODALITY_MISMATCH = "MODALITY_MISMATCH"
    CRS_MISMATCH = "CRS_MISMATCH"
    TEMPORAL_METADATA_MISSING = "TEMPORAL_METADATA_MISSING"
    TEMPORAL_INCOMPATIBILITY = "TEMPORAL_INCOMPATIBILITY"
    SPATIAL_MISMATCH = "SPATIAL_MISMATCH"
    TOOL_NOT_AVAILABLE = "TOOL_NOT_AVAILABLE"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    MODEL_FAILURE = "MODEL_FAILURE"


class ValidationIssue(BaseModel):
    code: ErrorCode
    message: str
    field: str | None = None


class ValidationResult(BaseModel):
    valid: bool

    errors: list[ValidationIssue] = Field(
        default_factory=list
    )

    warnings: list[str] = Field(
        default_factory=list
    )