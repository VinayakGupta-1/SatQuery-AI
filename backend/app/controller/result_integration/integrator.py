"""Stage 10 -- turning tool output into one unified result.

Different tools return very different things: an index tool returns a raster
and statistics, a detector will return boxes, a VQA model will return text.
This layer normalises all of them into the :class:`FinalResult` contract the
API and the frontend consume, so adding a tool never changes the response
shape.

It also normalises the *unhappy* paths. A task that was rejected by the
validator, blocked by the Registry, or that failed inside a tool returns the
same :class:`FinalResult` structure as a success, carrying an answer that says
plainly what happened. The frontend therefore has exactly one thing to render.

The integrator never computes anything and never fills a gap with a guess. If
a tool did not report a number, no sentence claims it.
"""

from __future__ import annotations

from typing import Any

from app.controller.execution.orchestrator import ExecutionResult
from app.controller.parameter_configuration.configurator import ParameterConfiguration
from app.controller.planning.planner import TaskPlan
from app.controller.tool_selection.selector import ToolSelectionResult
from app.registry.registry import get_tool
from app.schemas.errors import ValidationResult
from app.schemas.results import Evidence, ExecutionSummary, FinalResult, Finding, TaskResult
from app.schemas.spatiotemporal import QueryContext

from app.controller.result_integration.confidence import assess
from app.controller.result_integration.narrators import get_narrator


def format_bounds(bounds: list[float]) -> str:
    """``[west, south, east, north]`` in degrees, as a reader would write it."""
    west, south, east, north = bounds

    def lat(value: float) -> str:
        return f"{abs(value):.3f}° {'N' if value >= 0 else 'S'}"

    def lon(value: float) -> str:
        return f"{abs(value):.3f}° {'E' if value >= 0 else 'W'}"

    return f"{lat(south)} to {lat(north)}, {lon(west)} to {lon(east)}"


def context_findings(output: dict[str, Any], context: QueryContext | None) -> list[Finding]:
    """What was analysed, and whether it matches the place the question named."""
    metadata = output.get("metadata") or {}
    findings: list[Finding] = []
    aoi = metadata.get("aoi")
    if aoi:
        detail = f"{aoi.get('fraction_of_scene', 1.0):.0%} of the scene"
        if aoi.get("bounds_lonlat"):
            detail += f", {format_bounds(aoi['bounds_lonlat'])}"
        findings.append(Finding(title=f"Analysed area: {aoi.get('area')}", detail=detail + "."))
    if context is not None and context.locations:
        footprint = metadata.get("footprint_lonlat")
        where = (
            f"The imagery covers {format_bounds(footprint)}"
            if footprint else "The imagery carries no georeferencing"
        )
        places = ", ".join(context.locations)
        findings.append(
            Finding(
                title=f"Place named: {places}",
                detail=(
                    f"{where}. SatQuery does not look place names up, so check the "
                    f"imagery covers {'it' if len(context.locations) == 1 else 'them'}."
                ),
            )
        )
    return findings


class ResultIntegrator:
    """Assembles a :class:`FinalResult` from the outcome of a pipeline run."""

    def integrate(
        self,
        task_id: str,
        execution: ExecutionResult | None = None,
        query: str = "",
        plan: TaskPlan | None = None,
        selection: ToolSelectionResult | None = None,
        validation: ValidationResult | None = None,
        configuration: ParameterConfiguration | None = None,
        context: QueryContext | None = None,
    ) -> FinalResult:
        """Build the unified result for one task.

        ``confidence`` on the returned result is the weakest of the measured
        factors in its :class:`ConfidenceReport` -- how clearly the question
        mapped onto the tool, how much of the area could be observed, how well
        sensors agreed. It is never a claim about pixel accuracy that nothing
        measured, and a model-written answer from an unbenchmarked model gets
        no number at all.
        """
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id is required")
        if execution is not None and not isinstance(execution, ExecutionResult):
            raise TypeError("execution must be an ExecutionResult")

        summary = self._summarise(plan, selection, execution)

        if validation is not None and not validation.valid:
            return self._rejected(task_id, validation, summary)

        if execution is None:
            return self._not_executed(task_id, selection, configuration, summary)

        if execution.status == "completed":
            return self._completed(task_id, execution, selection, summary, validation, context)

        if execution.status == "authorised":
            return self._authorised(task_id, execution, selection, summary)

        return self._unsuccessful(task_id, execution, summary)

    # -- outcomes ----------------------------------------------------
    def _completed(
        self,
        task_id: str,
        execution: ExecutionResult,
        selection: ToolSelectionResult | None,
        summary: ExecutionSummary,
        validation: ValidationResult | None,
        context: QueryContext | None = None,
    ) -> FinalResult:
        output = execution.output if isinstance(execution.output, dict) else {}
        narrator = get_narrator(output.get("result_type"))

        tool_evidence = narrator.evidence(output)

        # The task-level result carries the tool's own provenance; the
        # top-level result additionally carries how the tool was chosen.
        evidence = list(tool_evidence)
        if selection is not None and selection.selection_reason:
            evidence.append(
                Evidence(
                    source="tool_selection",
                    description=selection.selection_reason,
                    confidence=selection.confidence,
                )
            )
        if validation is not None and validation.valid:
            evidence.append(
                Evidence(
                    source="input_validation",
                    description="Inputs passed every deterministic validation check.",
                )
            )

        result = TaskResult(
            result_type=output.get("result_type", "generic"),
            data={
                **(output.get("data") or {}),
                "statistics": output.get("statistics") or {},
                "artifacts": [
                    artifact["path"] for artifact in (output.get("artifacts") or [])
                ],
            },
            confidence=output.get("confidence"),
            evidence=tool_evidence,
        )

        definition = get_tool(execution.tool_id)
        report = assess(
            interpretation=selection.confidence if selection is not None else None,
            statistics=output.get("statistics"),
            engine=definition.engine.value if definition else "deterministic",
            model_identity=(output.get("metadata") or {}).get("vlm"),
        )

        return FinalResult(
            task_id=task_id,
            answer=narrator.answer(output),
            results=[result],
            confidence=report.score,
            evidence=evidence,
            execution_summary=summary,
            findings=narrator.findings(output) + context_findings(output, context),
            confidence_report=report,
        )

    @staticmethod
    def _not_executed(
        task_id: str,
        selection: ToolSelectionResult | None,
        configuration: ParameterConfiguration | None,
        summary: ExecutionSummary,
    ) -> FinalResult:
        """Explain a run that stopped before any tool was invoked."""
        evidence: list[Evidence] = []

        if configuration is not None and configuration.missing_parameters:
            missing = ", ".join(configuration.missing_parameters)
            answer = (
                "More information is needed before this task can run. The "
                f"following parameter(s) could not be determined: {missing}."
            )
            evidence = [
                Evidence(
                    source="parameter_configuration",
                    description=f"'{name}' was not supplied and has no derivable value.",
                )
                for name in configuration.missing_parameters
            ]
        elif configuration is not None and configuration.validation_errors:
            answer = "The task could not be configured. " + " ".join(
                configuration.validation_errors
            )
            evidence = [
                Evidence(source="parameter_configuration", description=message)
                for message in configuration.validation_errors
            ]
        elif selection is not None and selection.status != "selected":
            answer = (
                "The task did not reach execution. "
                + (selection.selection_reason or "No suitable tool was available.")
            )
            evidence = [
                Evidence(
                    source="tool_selection",
                    description=selection.selection_reason,
                    confidence=selection.confidence,
                )
            ]
        else:
            answer = "The task did not reach execution."

        return FinalResult(
            task_id=task_id,
            answer=answer,
            evidence=evidence,
            execution_summary=summary,
        )

    @staticmethod
    def _authorised(
        task_id: str,
        execution: ExecutionResult,
        selection: ToolSelectionResult | None,
        summary: ExecutionSummary,
    ) -> FinalResult:
        """Describe a dry run that passed every check and computed nothing."""
        evidence = [
            Evidence(
                source="execution:authorised",
                description="The Registry's execution policy cleared the request.",
            )
        ]
        if selection is not None and selection.selection_reason:
            evidence.append(
                Evidence(
                    source="tool_selection",
                    description=selection.selection_reason,
                    confidence=selection.confidence,
                )
            )
        return FinalResult(
            task_id=task_id,
            answer=(
                f"Dry run: the request passed every check, so '{execution.tool_id}' "
                "would run on this imagery. Nothing was computed."
            ),
            evidence=evidence,
            execution_summary=summary,
        )

    @staticmethod
    def _rejected(
        task_id: str,
        validation: ValidationResult,
        summary: ExecutionSummary,
    ) -> FinalResult:
        issues = validation.errors
        heading = (
            f"The supplied input was rejected before execution by "
            f"{len(issues)} validation check{'s' if len(issues) != 1 else ''}."
        )
        return FinalResult(
            task_id=task_id,
            answer=" ".join([heading] + [issue.message for issue in issues]),
            evidence=[
                Evidence(source=issue.code.value, description=issue.message)
                for issue in issues
            ],
            execution_summary=summary,
        )

    @staticmethod
    def _unsuccessful(
        task_id: str,
        execution: ExecutionResult,
        summary: ExecutionSummary,
    ) -> FinalResult:
        reason = execution.error or "No reason was reported."
        if execution.status == "blocked":
            answer = f"The task was blocked before the tool ran. {reason}"
        else:
            answer = f"The tool '{execution.tool_id}' did not complete. {reason}"

        return FinalResult(
            task_id=task_id,
            answer=answer,
            evidence=[Evidence(source=f"execution:{execution.status}", description=reason)],
            execution_summary=summary,
        )

    # -- helpers -----------------------------------------------------
    @staticmethod
    def _summarise(
        plan: TaskPlan | None,
        selection: ToolSelectionResult | None,
        execution: ExecutionResult | None,
    ) -> ExecutionSummary:
        steps = [step.description for step in plan.steps] if plan is not None else []

        tools: list[str] = []
        if execution is not None and execution.status == "completed":
            tools.append(execution.tool_id)
        elif selection is not None and selection.selected_tool_id:
            # The tool was chosen but never ran; naming it still explains the
            # attempt without claiming it produced anything.
            tools.append(selection.selected_tool_id)

        return ExecutionSummary(steps=steps, tools_used=tools)


__all__ = ["ResultIntegrator"]
