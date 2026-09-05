"""Building API responses from a pipeline run.

Kept apart from the routers so the shaping logic is testable without HTTP, and
apart from the controller so the controller never has to know about URLs.
"""

from __future__ import annotations

from typing import Any

from app.api.schemas import (
    AgentPlanOut,
    ArtifactLink,
    ExplanationOut,
    ImageSummary,
    TaskResponse,
    ValidationIssueOut,
    TaskStatus,
    ValidationReport,
    ValidationResponse,
)
from app.registry.registry import get_tool
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


def build_agent_plan(run: PipelineRun) -> AgentPlanOut | None:
    """Expose what the understanding layer proposed, including what was refused."""
    if run.agent is None:
        return None
    plan = run.agent.plan
    return AgentPlanOut(
        provider=plan.provider,
        task=plan.task,
        operation=plan.operation,
        proposed_tool=plan.tool,
        confidence=plan.confidence,
        clarification=run.clarification,
        reasoning=plan.reasoning,
        rejected_tools=list(run.agent.rejected_tools),
        rejected_parameters=list(run.agent.rejected_parameters),
        notes=list(run.agent.notes),
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

    tool_id = run.selection.selected_tool_id
    definition = get_tool(tool_id) if tool_id else None

    return TaskResponse(
        task_id=run.task_id,
        result_id=run.task_id,
        query=run.query,
        status=TaskStatus(run.status),
        outcome=run.outcome,
        answer=run.final.answer,
        task=run.understanding.task_type,
        tool=tool_id,
        tool_version=definition.version if definition else None,
        output_type=definition.output_type.value if definition else None,
        agent=build_agent_plan(run),
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
        status=TaskStatus(run.status),
        task_category=run.classification.task_category,
        selected_tool=run.selection.selected_tool_id,
        would_execute=run.validation.valid and run.selection.status == "selected",
        images=images,
        validation=build_validation_report(run.validation),
        explanation=build_explanation(run),
    )
