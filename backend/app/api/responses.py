"""Building API responses from a pipeline run.

Kept apart from the routers so the shaping logic is testable without HTTP, and
apart from the controller so the controller never has to know about URLs.
"""

from __future__ import annotations

from typing import Any

from app.api.schemas import (
    ArtifactLink,
    ExplanationOut,
    ImageSummary,
    TaskResponse,
    ValidationIssueOut,
    ValidationReport,
    ValidationResponse,
)
from app.controller.pipeline import PipelineRun
from app.schemas.errors import ValidationResult


def build_validation_report(validation: ValidationResult) -> ValidationReport:
    return ValidationReport(
        valid=validation.valid,
        errors=[
            ValidationIssueOut(
                code=issue.code.value, message=issue.message, field=issue.field
            )
            for issue in validation.errors
        ],
        warnings=list(validation.warnings),
    )


def build_explanation(run: PipelineRun) -> ExplanationOut:
    return ExplanationOut(
        understood_task=run.understanding.task_type,
        task_category=run.classification.task_category,
        plan_steps=[step.description for step in run.plan.steps],
        required_bands=list(run.requirements.required_bands),
        minimum_image_count=run.requirements.minimum_image_count,
        selected_tool=run.selection.selected_tool_id,
        selection_reason=run.selection.selection_reason,
        selection_confidence=run.selection.confidence,
        alternatives=[candidate.tool_id for candidate in run.selection.alternatives],
        resolved_parameters=(
            run.configuration.resolved_parameters if run.configuration else {}
        ),
        stage_status=run.stage_status(),
    )


def collect_artifacts(run: PipelineRun) -> dict[str, dict[str, Any]]:
    """Return the artifacts a run produced, keyed by artifact id."""
    if run.execution is None or not isinstance(run.execution.output, dict):
        return {}
    return {
        artifact["artifact_id"]: artifact
        for artifact in (run.execution.output.get("artifacts") or [])
    }


def build_task_response(
    run: PipelineRun,
    images: list[ImageSummary],
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> TaskResponse:
    """Shape a completed run into the public task response."""
    output = (
        run.execution.output
        if run.execution is not None and isinstance(run.execution.output, dict)
        else {}
    )
    artifacts = artifacts if artifacts is not None else collect_artifacts(run)

    data = dict(output.get("data") or {})
    data.pop("classes", None)  # returned separately below to keep both readable

    return TaskResponse(
        task_id=run.task_id,
        query=run.query,
        outcome=run.outcome,
        answer=run.final.answer,
        images=images,
        validation=build_validation_report(run.validation),
        explanation=build_explanation(run),
        statistics=output.get("statistics") or {},
        data={**data, "classes": (output.get("data") or {}).get("classes", {})},
        artifacts=[
            ArtifactLink(
                artifact_id=artifact_id,
                kind=artifact.get("kind", "raster"),
                format=artifact.get("format"),
                description=artifact.get("description", ""),
                # Never expose the server path; downloads go through the API.
                url=f"/api/tasks/{run.task_id}/artifacts/{artifact_id}",
            )
            for artifact_id, artifact in artifacts.items()
        ],
        evidence=run.final.evidence,
        confidence=run.final.confidence,
    )


def build_validation_response(
    run: PipelineRun, images: list[ImageSummary]
) -> ValidationResponse:
    """Shape a dry run, which deliberately stops before execution."""
    return ValidationResponse(
        query=run.query,
        task_category=run.classification.task_category,
        selected_tool=run.selection.selected_tool_id,
        would_execute=run.validation.valid and run.selection.status == "selected",
        images=images,
        validation=build_validation_report(run.validation),
        explanation=build_explanation(run),
    )
