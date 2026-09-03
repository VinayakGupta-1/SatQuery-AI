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
from app.schemas.errors import ValidationResult
from app.schemas.results import Evidence, ExecutionSummary, FinalResult, TaskResult

from app.controller.result_integration.narrators import get_narrator


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
    ) -> FinalResult:
        """Build the unified result for one task.

        ``confidence`` on the returned result describes how confidently the
        query was mapped onto the executed tool -- it is *not* a statement
        about the accuracy of the computed pixels. Deterministic arithmetic has
        no probabilistic confidence; the fraction of the scene that was
        actually computable is reported as evidence instead.
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
            return self._completed(task_id, execution, selection, summary, validation)

        return self._unsuccessful(task_id, execution, summary)

    # -- outcomes ----------------------------------------------------
    def _completed(
        self,
        task_id: str,
        execution: ExecutionResult,
        selection: ToolSelectionResult | None,
        summary: ExecutionSummary,
        validation: ValidationResult | None,
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

        return FinalResult(
            task_id=task_id,
            answer=narrator.answer(output),
            results=[result],
            confidence=selection.confidence if selection is not None else None,
            evidence=evidence,
            execution_summary=summary,
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
