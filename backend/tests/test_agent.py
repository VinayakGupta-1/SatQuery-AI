"""Tests for the query-understanding layer and its safety boundary.

The point of these is not that the agent understands English well -- that is
the rule engine's job and is tested elsewhere. The point is that whatever a
provider returns, however wrong or hostile, cannot reach execution.
"""

from __future__ import annotations

import json

import pytest

from app.agents.agent import QueryAgent, build_provider, to_task_understanding
from app.agents.guard import allowed_tool_ids, guard
from app.agents.providers import (
    OllamaProvider,
    ProviderError,
    QueryUnderstandingProvider,
    RuleBasedProvider,
)
from app.agents.schemas import AgentTaskPlan
from app.config.settings import Settings
from app.controller.task_understanding.task_understanding import TaskUnderstanding


# ============================================================
# STRUCTURED OUTPUT
# ============================================================
def test_the_agent_returns_a_structured_plan_not_free_text():
    decision = QueryAgent().understand("Calculate NDVI for this satellite image")

    assert isinstance(decision.plan, AgentTaskPlan)
    assert decision.plan.task == "ndvi"
    assert decision.plan.tool == "ndvi"
    assert decision.plan.operation == "index_computation"
    assert 0.0 <= decision.plan.confidence <= 1.0


@pytest.mark.parametrize(
    "query, expected_task, expected_tool",
    [
        ("Calculate NDVI for this image", "ndvi", "ndvi"),
        ("Show me the water bodies", "ndwi", "ndwi"),
        ("Find built-up area", "ndbi", "ndbi"),
        ("Compare these two images and find changes", "change_detection", "change_detection"),
    ],
)
def test_known_requests_map_to_registered_tools(query, expected_task, expected_tool):
    decision = QueryAgent().understand(query)
    assert decision.plan.task == expected_task
    assert decision.plan.tool == expected_tool


def test_an_empty_query_is_refused():
    with pytest.raises(ValueError):
        QueryAgent().understand("   ")


# ============================================================
# CLARIFICATION RATHER THAN GUESSWORK
# ============================================================
def test_an_unspecific_request_asks_for_clarification_instead_of_guessing():
    """"Analyze this image" names no analysis, so none may be invented."""
    decision = QueryAgent().understand("Analyze this image")

    assert decision.plan.clarification is not None
    assert decision.plan.tool is None
    # The question must actually help the user, not just say "unclear".
    assert "NDVI" in decision.plan.clarification


def test_an_unrecognised_request_does_not_fabricate_a_tool():
    decision = QueryAgent().understand("What is the capital of France")
    assert decision.plan.tool is None


# ============================================================
# THE GUARD -- HOSTILE AND MALFORMED PROVIDER OUTPUT
# ============================================================
def test_a_tool_that_is_not_registered_is_stripped():
    decision = guard(AgentTaskPlan(task="x", tool="os.system"))

    assert decision.plan.tool is None
    assert decision.rejected_tools == ["os.system"]
    assert "not in the registry" in decision.notes[0]


def test_a_registered_but_unimplemented_tool_is_stripped():
    """Proposing something that cannot run is as bad as inventing one."""
    decision = guard(AgentTaskPlan(task="vqa", tool="satellite_vqa"))

    assert decision.plan.tool is None
    assert decision.rejected_tools == ["satellite_vqa"]


def test_parameters_the_tool_does_not_declare_are_dropped():
    decision = guard(
        AgentTaskPlan(
            task="ndvi",
            tool="ndvi",
            parameters={"red_band": "B4", "__import__": "os", "shell": "rm -rf /"},
        )
    )

    assert decision.plan.parameters == {"red_band": "B4"}
    assert decision.rejected_parameters == ["__import__", "shell"]


def test_structured_parameter_values_are_dropped():
    """A nested object is not a legitimate parameter shape."""
    decision = guard(
        AgentTaskPlan(task="ndvi", tool="ndvi", parameters={"scale": {"exec": "x"}})
    )
    assert decision.plan.parameters == {}
    assert "scale" in decision.rejected_parameters


def test_an_out_of_range_confidence_is_clamped_not_trusted():
    assert AgentTaskPlan(task="x", confidence=9.9).confidence == 1.0
    assert AgentTaskPlan(task="x", confidence=-4).confidence == 0.0


def test_a_malformed_parameters_field_becomes_an_empty_dict():
    assert AgentTaskPlan(task="x", parameters="not-a-dict").parameters == {}
    assert AgentTaskPlan(task="x", parameters=["a"]).parameters == {}


def test_overlong_free_text_is_truncated():
    decision = guard(AgentTaskPlan(task="x", reasoning="A" * 10_000))
    assert len(decision.plan.reasoning) <= 512


def test_only_executable_tools_are_offered_to_a_provider():
    """The allowlist a model is shown never includes something that cannot run."""
    allowed = allowed_tool_ids()
    assert allowed == ["change_detection", "ndbi", "ndvi", "ndwi"]
    assert "satellite_vqa" not in allowed


# ============================================================
# PROVIDER SELECTION AND FAILURE
# ============================================================
def test_the_default_provider_is_the_free_rule_engine():
    assert build_provider(Settings()).name == "rules"


def test_an_unknown_provider_name_falls_back_to_rules_rather_than_failing():
    settings = Settings()
    settings.agent_provider = "some-paid-thing"
    assert build_provider(settings).name == "rules"


class _BrokenProvider(QueryUnderstandingProvider):
    name = "broken"

    def understand(self, query: str) -> AgentTaskPlan:
        raise ProviderError("the model is unreachable")


def test_a_failing_provider_degrades_to_rules_instead_of_failing_the_request():
    agent = QueryAgent(provider=_BrokenProvider())
    decision = agent.understand("Calculate NDVI")

    assert decision.plan.task == "ndvi"          # the rule engine took over
    assert decision.plan.provider == "rules"
    assert any("broken" in note for note in decision.notes)


def test_fallback_can_be_disabled_so_failures_surface():
    settings = Settings()
    settings.agent_fallback_to_rules = False
    agent = QueryAgent(provider=_BrokenProvider(), settings=settings)

    with pytest.raises(ProviderError):
        agent.understand("Calculate NDVI")


# ============================================================
# THE LOCAL MODEL PROVIDER (no network in these tests)
# ============================================================
def test_malformed_model_output_is_rejected_not_guessed_at():
    provider = OllamaProvider()
    for garbage in ("", "I think you want NDVI!", "[1, 2, 3]", "null"):
        with pytest.raises(ProviderError):
            provider._parse(garbage, "Calculate NDVI")


def test_model_output_missing_the_schema_is_rejected():
    provider = OllamaProvider()
    with pytest.raises(ProviderError):
        provider._parse(json.dumps({"confidence": "not-a-number"}), "q")


def test_well_formed_model_output_is_accepted_and_labelled():
    provider = OllamaProvider()
    plan = provider._parse(
        json.dumps({"task": "ndvi", "tool": "ndvi", "confidence": 0.9}),
        "Calculate NDVI",
    )
    assert plan.task == "ndvi"
    assert plan.provider == "ollama"


def test_a_model_cannot_claim_to_be_the_rule_engine():
    """``provider`` is stamped by the server, never taken from the model."""
    plan = OllamaProvider()._parse(json.dumps({"task": "ndvi", "provider": "rules"}), "q")
    assert plan.provider == "ollama"


# ============================================================
# THE ADAPTER INTO THE DETERMINISTIC CHAIN
# ============================================================
@pytest.mark.parametrize(
    "query",
    [
        "Calculate NDVI",
        "Find water bodies",
        "Compare two images for change",
        "Detect buildings",
        "Analyze this image",
        "zzzz nonsense",
    ],
)
def test_the_rule_provider_round_trips_to_identical_understanding(query):
    """Enabling the agent layer must not change deterministic behaviour.

    The rule provider is built from ``TaskUnderstanding``, so adapting its plan
    back has to reproduce that object exactly -- otherwise routing the pipeline
    through the agent would silently alter every downstream stage.
    """
    direct = TaskUnderstanding().understand(query)
    through_agent = to_task_understanding(RuleBasedProvider().understand(query), query)

    assert through_agent.model_dump() == direct.model_dump()
