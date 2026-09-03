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


class PipelineRun(BaseModel):
    """Everything the pipeline produced, stage by stage.

    Keeping every intermediate result is what makes the system explainable:
    the API can show precisely why a tool was chosen or why input was refused,
    instead of only the final answer.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    query: str
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

    def __init__(self) -> None:
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

        # Stages 1-4: interpret the request.
        understanding = self.understanding.understand(query)
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

        return PipelineRun(
            task_id=task_id,
            query=query,
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


__all__ = ["PipelineRun", "SatQueryPipeline"]
