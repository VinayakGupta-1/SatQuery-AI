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

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

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
)
from app.controller.tool_selection.selector import ToolSelectionResult, ToolSelector
from app.registry.registry import get_tool
from app.schemas.errors import ValidationResult
from app.schemas.inputs import ImageInput
from app.schemas.results import FinalResult
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

    @property
    def succeeded(self) -> bool:
        return self.execution is not None and self.execution.status == "completed"

    @property
    def outcome(self) -> str:
        """A single word for how the run ended, for API consumers.

        ``rejected`` and ``needs_input`` are distinct on purpose: the first
        means the imagery is wrong for the task, the second means the request
        is answerable once more information arrives.
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
        if outcome == "completed":
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
    ) -> PipelineRun:
        """Run every stage in order and return the complete record."""
        task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"

        # Stages 1-4: interpret the request. The agent proposes; the guard
        # has already stripped anything the registry does not sanction.
        decision = self.agent.understand(query)
        understanding = to_task_understanding(decision.plan, query)
        classification = self.classifier.classify(understanding)
        plan = self.planner.create_plan(understanding, classification)
        requirements = self.requirements.resolve(understanding, classification, plan)

        # Stage 6 runs before stage 5 on purpose: the chosen tool's registry
        # entry supplies the image ceiling the validator then enforces.
        selection = self.selector.select(
            understanding, classification, plan, requirements
        )
        tool = get_tool(selection.selected_tool_id) if selection.selected_tool_id else None

        # Stage 5: the deterministic gate.
        validation = validate_inputs(
            images, to_validation_requirements(requirements, tool)
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
            if configuration.status == "configured":
                # Stages 8-9: enforce registry policy, then compute.
                execution = self.orchestrator.execute(
                    ExecutionRequest(
                        tool_id=configuration.tool_id,
                        parameters=configuration.resolved_parameters,
                        input_references=[image.path for image in images],
                        output_directory=output_directory,
                    )
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
        )

        logger.info(
            "task complete",
            extra={
                "task_id": task_id,
                "status": final_status(validation, selection, configuration, execution),
                "tool": selection.selected_tool_id,
                "images": len(images),
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
        )


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
    if execution.status == "completed":
        return "success"
    if execution.status == "blocked":
        return "needs_clarification"
    return "execution_error"


__all__ = ["PipelineRun", "SatQueryPipeline", "final_status"]
