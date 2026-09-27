"""The SatQuery controller pipeline -- all ten stages, composed in order.

Each stage is independently implemented and independently tested. This module
is the one place that knows their order and how the output of each becomes the
input of the next, so nothing else -- not the API, not a test, not a future
agent -- has to reassemble that knowledge.

The pipeline short-circuits honestly. If validation rejects the input, no tool
runs; if no tool is selected, nothing is configured. Every path still returns a
:class:`PipelineRun` carrying a :class:`FinalResult`, so callers have exactly
one shape to handle.

An LLM will eventually sit *around* this pipeline rather than inside it: it may
propose the query interpretation or the parameters, but the validator, the
registry and the executor stay in the path and keep their veto.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent import QueryAgent, to_task_understanding
from app.agents.schemas import GuardDecision
from app.config.logging_config import get_logger
from app.controller.execution.orchestrator import (
    ExecutionOrchestrator,
    ExecutionRequest,
    ExecutionResult,
)
from app.controller.input_requirements.input_requirements import (
    InputRequirements,
    InputRequirementsResolver,
)
from app.controller.input_requirements.validation_bridge import to_validation_requirements
from app.controller.parameter_configuration.configurator import (
    ParameterConfiguration,
    ParameterConfigurator,
)
from app.controller.planning.planner import Planner, TaskPlan
from app.controller.result_integration.integrator import ResultIntegrator
from app.controller.task_classification.task_classification import (
    TaskClassificationResult,
    TaskClassifier,
)
from app.controller.task_understanding.task_understanding import (
    TaskUnderstanding,
    TaskUnderstandingResult,
    adapt_to_imagery,
)
from app.controller.tool_selection.selector import ToolSelectionResult, ToolSelector
from app.registry.registry import get_tool
from app.schemas.errors import ValidationResult
from app.schemas.inputs import ImageInput
from app.schemas.results import FinalResult, TraceEvent, TraceStep
from app.validator.validator import validate_inputs

logger = get_logger("pipeline")


class PipelineRun(BaseModel):
    """Everything the pipeline produced, stage by stage.

    Keeping every intermediate result is what makes the system explainable:
    the API can show precisely why a tool was chosen or why input was refused,
    instead of only the final answer.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    query: str
    #: What the understanding layer proposed and what the guard allowed. The
    #: proposal is recorded even when it was overruled, so the audit trail
    #: shows the refusal rather than hiding it.
    agent: GuardDecision | None = None
    understanding: TaskUnderstandingResult
    classification: TaskClassificationResult
    plan: TaskPlan
    requirements: InputRequirements
    selection: ToolSelectionResult
    validation: ValidationResult
    configuration: ParameterConfiguration | None = None
    execution: ExecutionResult | None = None
    final: FinalResult
    #: Every stage as it actually ran, timed, with the tool's own steps inside
    #: the execution stage. The same run, told in order.
    trace: list[TraceEvent] = Field(default_factory=list)

    @property
    def route(self) -> str:
        """Which engine answered: ``deterministic``, ``vlm`` or ``hybrid``.

        Taken from the selected tool's registry entry when there is one --
        that is the authoritative statement -- and from the plan otherwise.
        """
        tool = get_tool(self.selection.selected_tool_id) if self.selection.selected_tool_id else None
        return tool.engine.value if tool is not None else self.plan.route

    @property
    def succeeded(self) -> bool:
        return self.execution is not None and self.execution.status == "completed"

    @property
    def would_execute(self) -> bool:
        """Whether the tool ran, or -- on a dry run -- was cleared to run."""
        return self.execution is not None and self.execution.status in {
            "authorised",
            "completed",
        }

    @property
    def outcome(self) -> str:
        """A single word for how the run ended, for API consumers.

        ``rejected`` and ``needs_input`` are distinct on purpose: the first
        means the imagery is wrong for the task, the second means the request
        is answerable once more information arrives. ``authorised`` is the
        outcome of a dry run that passed every check and stopped before the
        tool was called.
        """
        if not self.validation.valid:
            return "rejected"
        if self.selection.status != "selected":
            return "requires_clarification"
        if self.configuration is not None and self.configuration.status == "needs_input":
            return "needs_input"
        if self.configuration is not None and self.configuration.status == "invalid":
            return "invalid_parameters"
        if self.execution is None:
            return "not_executed"
        return self.execution.status

    @property
    def status(self) -> str:
        """Collapse ``outcome`` into the four states a frontend renders.

        ``outcome`` stays precise for operators; this stays stable for the UI,
        so adding an internal outcome never breaks the frontend contract.
        """
        outcome = self.outcome
        if outcome in {"completed", "authorised"}:
            return "success"
        if outcome == "rejected":
            return "validation_error"
        # ``blocked`` means registry policy refused before any computation --
        # most often because the selected capability has no implementation
        # bound. That is a gap in what the system can do, not a failure of the
        # run, so the user is asked for something it *can* do rather than
        # shown an error.
        if outcome in {"requires_clarification", "needs_input", "blocked", "not_executed"}:
            return "needs_clarification"
        return "execution_error"

    @property
    def clarification(self) -> str | None:
        """The question to put back to the user, when one is needed."""
        if self.status != "needs_clarification":
            return None
        if self.agent is not None and self.agent.plan.clarification:
            return self.agent.plan.clarification
        if self.selection.status != "selected":
            return self.selection.selection_reason or (
                "The request could not be matched to an available capability."
            )
        if self.execution is not None and self.execution.status == "blocked":
            # The orchestrator's message names the capability and lists what
            # can actually run, which is exactly what the user needs.
            return self.execution.error
        if self.configuration is not None and self.configuration.status == "needs_input":
            return "More information is required before this task can run."
        return "More information is required before this task can run."

    @property
    def refusal(self) -> str | None:
        """Why the tool did not run, or would not run, in one sentence.

        ``None`` when it ran or was cleared to. A dry-run caller needs exactly
        this: not the tool that was selected, but what stood in its way.
        """
        if self.would_execute:
            return None
        if not self.validation.valid:
            return " ".join(issue.message for issue in self.validation.errors)
        if self.status == "needs_clarification":
            return self.clarification
        if self.configuration is not None and self.configuration.validation_errors:
            return " ".join(self.configuration.validation_errors)
        if self.execution is not None and self.execution.error:
            return self.execution.error
        return self.final.answer

    def stage_status(self) -> dict[str, str]:
        """Summarise how far the run got, for diagnostics and the API."""
        return {
            "understanding": self.understanding.task_type or "unrecognised",
            "classification": self.classification.task_category,
            "planning": self.plan.status,
            "validation": "valid" if self.validation.valid else "rejected",
            "tool_selection": self.selection.status,
            "parameter_configuration": (
                self.configuration.status if self.configuration else "not_reached"
            ),
            "execution": self.execution.status if self.execution else "not_reached",
        }


class SatQueryPipeline:
    """Runs a natural-language query against a set of images."""

    def __init__(self, agent: QueryAgent | None = None) -> None:
        #: Interprets the sentence. Its output is guarded before use and can
        #: never reach execution without passing the validator.
        self.agent = agent or QueryAgent()
        self.understanding = TaskUnderstanding()
        self.classifier = TaskClassifier()
        self.planner = Planner()
        self.requirements = InputRequirementsResolver()
        self.selector = ToolSelector()
        self.configurator = ParameterConfigurator()
        self.orchestrator = ExecutionOrchestrator()
        self.integrator = ResultIntegrator()

    def run(
        self,
        query: str,
        images: list[ImageInput],
        task_id: str | None = None,
        output_directory: str | None = None,
        user_parameters: dict[str, Any] | None = None,
        execute: bool = True,
    ) -> PipelineRun:
        """Run every stage in order and return the complete record.

        With ``execute=False`` this is a dry run: every stage up to and
        including the Registry's execution policy runs exactly as it would for
        real, and the tool itself is never called, so nothing is computed and
        nothing is written.
        """
        task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        trace = _Tracer()

        # Stages 1-4: interpret the request. The agent proposes; the guard
        # has already stripped anything the registry does not sanction.
        decision = self.agent.understand(query)
        understanding = to_task_understanding(decision.plan, query)
        trace.record(
            "understanding",
            understanding.task_type or "unrecognised",
            "; ".join(
                part for part in (f"{decision.plan.provider} provider", _describe_context(understanding)) if part
            ),
        )
        # Some requests mean different measurements on different sensors --
        # water is NDWI on optical imagery and backscatter on radar -- and only
        # the uploaded files can say which sensor this is.
        understanding, adaptation = adapt_to_imagery(
            understanding,
            {image.metadata.modality if image.metadata else None for image in images},
        )
        if adaptation:
            decision.notes.append(adaptation)
            trace.record("adaptation", "adapted", adaptation)
        classification = self.classifier.classify(understanding)
        trace.record("classification", classification.task_category)
        plan = self.planner.create_plan(understanding, classification)
        trace.record("planning", plan.status, f"route: {plan.route}; {len(plan.steps)} steps")
        requirements = self.requirements.resolve(understanding, classification, plan)
        trace.record("input_requirements", "resolved", _describe_requirements(requirements))

        # Stage 6 runs before stage 5 on purpose: the chosen tool's registry
        # entry supplies the image ceiling the validator then enforces.
        selection = self.selector.select(
            understanding, classification, plan, requirements
        )
        tool = get_tool(selection.selected_tool_id) if selection.selected_tool_id else None
        trace.record(
            "tool_selection",
            selection.status,
            f"{tool.tool_id} ({tool.engine.value} engine)" if tool else selection.selection_reason,
        )

        # Stage 5: the deterministic gate.
        validation = validate_inputs(
            images, to_validation_requirements(requirements, tool)
        )
        trace.record(
            "validation",
            "valid" if validation.valid else "rejected",
            f"{len(images)} image(s); {len(validation.errors)} error(s), "
            f"{len(validation.warnings)} warning(s)"
            + (f": {validation.errors[0].message}" if validation.errors else ""),
        )

        configuration: ParameterConfiguration | None = None
        execution: ExecutionResult | None = None

        if validation.valid and selection.status == "selected":
            # Stage 7: decide the exact parameters.
            configuration = self.configurator.configure(
                understanding,
                classification,
                plan,
                requirements,
                selection,
                user_parameters,
            )
            trace.record(
                "parameter_configuration",
                configuration.status,
                f"{len(configuration.resolved_parameters)} parameter(s) resolved"
                if configuration.status == "configured"
                else " ".join(configuration.validation_errors + configuration.missing_parameters),
            )
            if configuration.status == "configured":
                request = ExecutionRequest(
                    tool_id=configuration.tool_id,
                    parameters=configuration.resolved_parameters,
                    input_references=[image.path for image in images],
                    output_directory=output_directory,
                )
                # Stages 8-9: enforce registry policy, then compute. A dry run
                # stops between the two.
                execution = (
                    self.orchestrator.execute(request)
                    if execute
                    else self.orchestrator.authorise(request)
                )
                trace.record(
                    "execution",
                    execution.status,
                    execution.error or f"{execution.tool_id} on the {tool.engine.value} engine",
                    steps=execution.execution_metadata.get("steps"),
                )

        # Stage 10: one result shape for every outcome.
        final = self.integrator.integrate(
            task_id=task_id,
            execution=execution,
            query=query,
            plan=plan,
            selection=selection,
            validation=validation,
            configuration=configuration,
            context=understanding.context,
        )
        report = final.confidence_report
        trace.record(
            "result_integration",
            "integrated",
            f"{len(final.findings)} finding(s)"
            + (f"; confidence {report.level}" if report is not None else ""),
        )

        logger.info(
            "task complete",
            extra={
                "task_id": task_id,
                "status": final_status(validation, selection, configuration, execution),
                "tool": selection.selected_tool_id,
                "images": len(images),
                "duration_ms": round(sum(event.duration_ms for event in trace.events), 1),
            },
        )

        return PipelineRun(
            task_id=task_id,
            query=query,
            agent=decision,
            understanding=understanding,
            classification=classification,
            plan=plan,
            requirements=requirements,
            selection=selection,
            validation=validation,
            configuration=configuration,
            execution=execution,
            final=final,
            trace=trace.events,
        )


class _Tracer:
    """Times each stage from the end of the one before it."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._since = time.perf_counter()

    def record(
        self,
        stage: str,
        status: str,
        detail: str = "",
        steps: list[dict[str, Any]] | None = None,
    ) -> None:
        now = time.perf_counter()
        self.events.append(
            TraceEvent(
                stage=stage,
                status=status,
                detail=detail,
                duration_ms=round((now - self._since) * 1000, 1),
                steps=[TraceStep(**step) for step in steps or []],
            )
        )
        self._since = now


def _describe_context(understanding: TaskUnderstandingResult) -> str:
    context = understanding.context
    parts = []
    if context.time_range is not None:
        parts.append(f"period {context.time_range.describe()}")
    if context.aoi is not None:
        parts.append(f"area: {context.aoi.describe()}")
    if context.metrics:
        parts.append("metrics: " + ", ".join(context.metrics))
    if context.modality:
        parts.append(f"modality: {context.modality}")
    if context.locations:
        parts.append("places: " + ", ".join(context.locations))
    return "; ".join(parts)


def _describe_requirements(requirements: InputRequirements) -> str:
    parts = [f"at least {requirements.minimum_image_count} image(s)"]
    modalities = [m for m in requirements.required_modalities if not m.startswith("compatible")]
    if modalities:
        parts.append("modality " + " + ".join(modalities))
    bands = [b for b in requirements.required_bands if b != "required_spectral_bands"]
    if bands:
        parts.append("bands " + ", ".join(bands))
    if requirements.time_range is not None:
        parts.append(f"acquired {requirements.time_range.describe()}")
    if requirements.max_days_between_images is not None:
        parts.append(f"within {requirements.max_days_between_images} days of each other")
    return "; ".join(parts)


def final_status(validation, selection, configuration, execution) -> str:
    """Derive the coarse status without building a ``PipelineRun`` first."""
    if not validation.valid:
        return "validation_error"
    if selection.status != "selected":
        return "needs_clarification"
    if configuration is not None and configuration.status == "needs_input":
        return "needs_clarification"
    if execution is None:
        return "needs_clarification"
    if execution.status in {"completed", "authorised"}:
        return "success"
    if execution.status == "blocked":
        return "needs_clarification"
    return "execution_error"


__all__ = ["PipelineRun", "SatQueryPipeline", "final_status"]
