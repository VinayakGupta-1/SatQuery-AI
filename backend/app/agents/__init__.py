"""The natural-language understanding layer.

The agent proposes; the registry, the validator and the executor dispose. It
cannot run code, touch the filesystem, or reach anything but a locally
configured model endpoint, and everything it returns is filtered through
:mod:`app.agents.guard` before the pipeline acts on it.
"""

from app.agents.agent import QueryAgent, build_provider
from app.agents.guard import allowed_tool_ids, guard
from app.agents.providers import (
    OllamaProvider,
    ProviderError,
    QueryUnderstandingProvider,
    RuleBasedProvider,
)
from app.agents.schemas import AgentTaskPlan, GuardDecision

__all__ = [
    "AgentTaskPlan",
    "GuardDecision",
    "OllamaProvider",
    "ProviderError",
    "QueryAgent",
    "QueryUnderstandingProvider",
    "RuleBasedProvider",
    "allowed_tool_ids",
    "build_provider",
    "guard",
]
