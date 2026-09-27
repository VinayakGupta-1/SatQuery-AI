from typing import Any

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str
    description: str
    confidence: float | None = None


class Finding(BaseModel):
    """One grounded fact from the result: what, how much, and where.

    Findings are the answer broken into checkable parts. Each is derived from
    numbers the tool reported; ``location`` places it in the scene -- a
    compass sector and, when the imagery is georeferenced, longitude and
    latitude.
    """

    title: str
    detail: str = ""
    location: dict[str, Any] | None = None


class ConfidenceFactor(BaseModel):
    """One measured ingredient of the confidence score."""

    name: str
    score: float
    detail: str


class ConfidenceReport(BaseModel):
    """How far the answer can be trusted, and why.

    ``score`` is the weakest of the measured factors, so it can always be
    traced to one number: the query was ambiguous, most of the scene was
    cloud, or the sensors disagreed. It is not a calibrated probability.
    A model-generated answer whose model has no recorded benchmark accuracy
    gets no score at all -- level ``unrated`` -- rather than an invented one.
    """

    score: float | None = None
    level: str
    basis: str
    factors: list[ConfidenceFactor] = Field(default_factory=list)


class TraceStep(BaseModel):
    """A step a tool took inside one execution."""

    name: str
    detail: str = ""
    duration_ms: float = 0.0


class TraceEvent(BaseModel):
    """One pipeline stage as it actually ran."""

    stage: str
    status: str
    detail: str = ""
    duration_ms: float = 0.0
    steps: list[TraceStep] = Field(default_factory=list)


class TaskResult(BaseModel):
    result_type: str
    data: Any

    confidence: float | None = None

    evidence: list[Evidence] = Field(
        default_factory=list
    )


class ExecutionSummary(BaseModel):
    steps: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)


class FinalResult(BaseModel):
    task_id: str
    answer: str

    results: list[TaskResult] = Field(
        default_factory=list
    )

    confidence: float | None = None

    evidence: list[Evidence] = Field(
        default_factory=list
    )

    execution_summary: ExecutionSummary

    findings: list[Finding] = Field(default_factory=list)

    confidence_report: ConfidenceReport | None = None
