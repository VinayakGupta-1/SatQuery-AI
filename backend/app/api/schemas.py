"""Response models for the HTTP API.

These are separate from the controller's internal models on purpose. The API
must not leak server filesystem paths, and it should stay stable while the
controller evolves, so artifacts are exposed as URLs and stage output is
reshaped into a form a frontend can render directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.results import Evidence


class ToolSummary(BaseModel):
    """One entry from the controlled tool registry."""

    tool_id: str
    name: str
    description: str
    tool_type: str
    supported_modalities: list[str] = Field(default_factory=list)
    required_bands: list[str] = Field(default_factory=list)
    min_images: int
    max_images: int
    requires_temporal_pair: bool
    parameters: dict[str, str] = Field(default_factory=dict)
    enabled: bool
    #: False when the tool is registered but has no implementation bound yet.
    implemented: bool


class ImageSummary(BaseModel):
    """What the server determined about one uploaded raster."""

    id: str
    filename: str
    width: int | None = None
    height: int | None = None
    crs: str | None = None
    modality: str | None = None
    sensor: str | None = None
    bands: list[str] = Field(default_factory=list)
    acquisition_date: str | None = None


class ValidationIssueOut(BaseModel):
    code: str
    message: str
    field: str | None = None


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssueOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ArtifactLink(BaseModel):
    """A downloadable file produced by a tool."""

    artifact_id: str
    kind: str
    format: str | None = None
    description: str = ""
    url: str


class ExplanationOut(BaseModel):
    """Why the system did what it did -- the auditable trail.

    This is what separates a controlled pipeline from a black box, so it is a
    first-class part of the response rather than debug output.
    """

    understood_task: str | None = None
    task_category: str
    plan_steps: list[str] = Field(default_factory=list)
    required_bands: list[str] = Field(default_factory=list)
    minimum_image_count: int = 0
    selected_tool: str | None = None
    selection_reason: str = ""
    selection_confidence: float = 0.0
    alternatives: list[str] = Field(default_factory=list)
    resolved_parameters: dict[str, Any] = Field(default_factory=dict)
    stage_status: dict[str, str] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    """The full result of one task, success or otherwise."""

    task_id: str
    query: str
    outcome: str
    answer: str
    images: list[ImageSummary] = Field(default_factory=list)
    validation: ValidationReport
    explanation: ExplanationOut
    statistics: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactLink] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = None


class TaskListEntry(BaseModel):
    task_id: str
    query: str
    outcome: str
    answer: str


class ValidationResponse(BaseModel):
    """The result of a dry-run check that never executes a tool."""

    query: str
    task_category: str
    selected_tool: str | None = None
    would_execute: bool
    images: list[ImageSummary] = Field(default_factory=list)
    validation: ValidationReport
    explanation: ExplanationOut


class BackendInfo(BaseModel):
    raster_backend: str
    numpy_available: bool
    supports_compressed_geotiff: bool


class HealthResponse(BaseModel):
    status: str
    registered_tools: int
    implemented_tools: list[str]
    backend: BackendInfo
