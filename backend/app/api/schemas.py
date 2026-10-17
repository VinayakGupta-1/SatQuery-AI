"""Response models for the HTTP API.

These are separate from the controller's internal models on purpose. The API
must not leak server filesystem paths, and it should stay stable while the
controller evolves, so artifacts are exposed as URLs and stage output is
reshaped into a form a frontend can render directly.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.acquisition import AcquisitionReport
from app.schemas.results import ConfidenceReport, Evidence, Finding, TraceEvent


class TaskStatus(str, Enum):
    """The four outcomes a frontend has to render.

    ``outcome`` on the response carries the precise internal reason; this is
    the coarse status a UI switches on, so a new internal outcome never breaks
    the frontend contract.
    """

    SUCCESS = "success"
    NEEDS_CLARIFICATION = "needs_clarification"
    VALIDATION_ERROR = "validation_error"
    EXECUTION_ERROR = "execution_error"


class ToolSummary(BaseModel):
    """One entry from the controlled tool registry."""

    tool_id: str
    name: str
    description: str
    tool_type: str
    version: str
    output_type: str
    supported_modalities: list[str] = Field(default_factory=list)
    required_bands: list[str] = Field(default_factory=list)
    min_images: int
    max_images: int
    requires_temporal_pair: bool
    parameters: dict[str, str] = Field(default_factory=dict)
    enabled: bool
    #: ``deterministic``, ``vlm`` or ``hybrid``: which side of the core answers.
    engine: str = "deterministic"
    #: False when the tool cannot run in this deployment: no implementation is
    #: bound yet, or the one that is bound is switched off.
    implemented: bool
    #: True when an implementation is bound, even if it is switched off -- so
    #: "not built yet" and "built but off" can be told apart.
    bound: bool = False
    #: Why ``implemented`` is false, phrased for an operator; ``None`` otherwise.
    availability_note: str | None = None


class ImageSummary(BaseModel):
    """What the server determined about one uploaded raster.

    Read from the file itself, never from the client, so a caller cannot
    describe their SAR scene as optical to slip past validation. The extra
    geospatial fields are here because a frontend needs them to draw a map:
    resolution and bounds place the raster on the ground.
    """

    id: str
    filename: str
    width: int | None = None
    height: int | None = None
    band_count: int | None = None
    dtype: str | None = None
    nodata: float | None = None
    crs: str | None = None
    #: GDAL geotransform: (origin_x, pixel_w, row_rot, origin_y, col_rot, pixel_h).
    transform: list[float] | None = None
    #: Ground sample distance as (x, y), in CRS units.
    resolution: list[float] | None = None
    #: (min_x, min_y, max_x, max_y) in CRS units.
    bounds: list[float] | None = None
    modality: str | None = None
    sensor: str | None = None
    bands: list[str] = Field(default_factory=list)
    acquisition_date: str | None = None
    #: The footprint as ``[west, south, east, north]`` in degrees, when the
    #: CRS can be transformed -- so a user can check it covers their place.
    bounds_lonlat: list[float] | None = None


class UnderstandingOut(BaseModel):
    """What the question was read as, beyond its task."""

    intent: str | None = None
    #: Place names as written. Reported, never geocoded.
    locations: list[str] = Field(default_factory=list)
    #: The area of interest, in words, when the question named one.
    area: str | None = None
    #: The period the question names, in words.
    period: str | None = None
    metrics: list[str] = Field(default_factory=list)
    #: What the sentence says about the sensor.
    query_modality: str | None = None
    #: What the uploaded imagery actually is.
    imagery_modality: str | None = None


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


class AgentPlanOut(BaseModel):
    """What the understanding layer proposed, and what the guard allowed.

    Published rather than hidden: a user is entitled to see that the model
    suggested something the registry refused.
    """

    provider: str
    task: str | None = None
    operation: str | None = None
    proposed_tool: str | None = None
    confidence: float = 0.0
    clarification: str | None = None
    reasoning: str = ""
    rejected_tools: list[str] = Field(default_factory=list)
    rejected_parameters: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TaskResponse(BaseModel):
    """The full result of one task, success or otherwise."""

    task_id: str
    #: Stable identifier of this result. Equal to ``task_id`` today; kept
    #: separate so a future re-run of one task can produce several results.
    result_id: str
    query: str
    #: Coarse status a frontend switches on.
    status: TaskStatus
    #: The precise internal reason, e.g. ``rejected`` or ``needs_input``.
    outcome: str
    answer: str
    task: str | None = None
    tool: str | None = None
    tool_version: str | None = None
    output_type: str | None = None
    agent: AgentPlanOut | None = None
    images: list[ImageSummary] = Field(default_factory=list)
    validation: ValidationReport
    explanation: ExplanationOut
    statistics: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactLink] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    #: The weakest measured confidence factor; ``None`` when unrated.
    confidence: float | None = None
    #: ``deterministic``, ``vlm`` or ``hybrid``: which engine answered.
    route: str = "deterministic"
    understood: UnderstandingOut = Field(default_factory=UnderstandingOut)
    #: The answer broken into grounded parts: what, how much, where.
    findings: list[Finding] = Field(default_factory=list)
    confidence_report: ConfidenceReport | None = None
    #: Every pipeline stage as it ran, timed, with the tool's own steps.
    trace: list[TraceEvent] = Field(default_factory=list)
    #: Where the imagery came from, when SatQuery fetched it rather than the
    #: user uploading it: the place, the period searched, each scene chosen.
    acquisition: AcquisitionReport | None = None


class TaskListEntry(BaseModel):
    task_id: str
    query: str
    status: TaskStatus
    outcome: str
    answer: str


class ValidationResponse(BaseModel):
    """The result of a dry-run check that never executes a tool."""

    query: str
    status: TaskStatus
    task_category: str
    selected_tool: str | None = None
    #: True only when every stage, including the Registry's execution policy,
    #: cleared the request. The tool itself is never run to find out.
    would_execute: bool
    #: When ``would_execute`` is false: what stands in the way, in one sentence.
    reason: str | None = None
    images: list[ImageSummary] = Field(default_factory=list)
    validation: ValidationReport
    explanation: ExplanationOut
    route: str = "deterministic"
    understood: UnderstandingOut = Field(default_factory=UnderstandingOut)
    trace: list[TraceEvent] = Field(default_factory=list)


class BackendInfo(BaseModel):
    raster_backend: str
    numpy_available: bool
    supports_compressed_geotiff: bool


class AuthInfo(BaseModel):
    """How the workspace signs users in. Every value here is public by design:
    the project URL and publishable key identify the project, and row level
    security decides what a key can do."""

    provider: str = "supabase"
    url: str
    publishable_key: str
    #: New accounts must confirm their email address before they can sign in.
    email_verification: bool = True


class CapabilitiesResponse(BaseModel):
    """Everything SatQuery can currently do, straight from the registry.

    Generated, never hand-maintained: a tool that is registered appears here,
    and one that cannot run appears with ``implemented`` false rather than
    being quietly listed as available.
    """

    version: str
    #: Tool ids that can actually execute right now.
    executable: list[str] = Field(default_factory=list)
    #: Every registered tool, executable or not.
    tools: list[ToolSummary] = Field(default_factory=list)
    #: Raster formats the ingestion layer accepts.
    accepted_formats: list[str] = Field(default_factory=list)
    max_upload_bytes: int
    max_images_per_task: int
    #: Which understanding provider is active. Never the credential itself.
    agent_provider: str
    #: True when a hosted model is configured and in use. The key is never
    #: exposed -- only whether one is present.
    agent_llm_enabled: bool
    #: ``hosted`` or ``ollama`` when the vision-language model core is on;
    #: ``None`` when it is switched off.
    vlm_provider: str | None = None
    #: True when the vision model runs on this machine, so no imagery leaves it.
    vlm_local: bool = False
    #: True when a request may arrive without imagery: SatQuery then fetches
    #: Sentinel-2 or Sentinel-1 scenes for the place the question names.
    auto_fetch: bool = False
    #: Present when users must sign in; ``None`` when the API is open.
    auth: AuthInfo | None = None
    backend: "BackendInfo"


class HealthResponse(BaseModel):
    status: str
    registered_tools: int
    implemented_tools: list[str]
    backend: BackendInfo
