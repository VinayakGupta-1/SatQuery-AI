"""The query agent: choose a provider, run it, then refuse to trust it.

The agent is the only component allowed to interpret a user's sentence, and it
is deliberately the least privileged component in the system. It returns a
description of what the user appears to want. It cannot run a tool, read a
file, reach the filesystem, or reach the network beyond a locally configured
model endpoint.

Everything it proposes is passed through :mod:`app.agents.guard` before the
rest of the pipeline sees it, and the deterministic validator still has the
final say over whether anything executes.
"""

from __future__ import annotations

import time

from app.agents.guard import guard
from app.agents.providers import (
    HostedProvider,
    OllamaProvider,
    ProviderError,
    QueryUnderstandingProvider,
    RuleBasedProvider,
)
from app.agents.schemas import AgentTaskPlan, GuardDecision
from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings

logger = get_logger("agent")


def build_provider(settings: Settings | None = None) -> QueryUnderstandingProvider:
    """Return the provider named by configuration.

    An unrecognised provider name falls back to rules rather than failing
    startup: a typo in an environment variable should degrade understanding,
    not take the service down.
    """
    settings = settings or get_settings()
    name = settings.resolved_agent_provider

    if name == "ollama":
        return OllamaProvider(
            model=settings.agent_model,
            base_url=settings.agent_base_url,
            timeout=settings.agent_timeout_seconds,
        )

    if name == "hosted":
        if not settings.has_agent_api_key:
            # Only reachable when "hosted" was forced without a key. Falling
            # back keeps the service up; the operator is told why.
            logger.warning(
                "hosted provider requested but no API key is configured; "
                "using the rule engine"
            )
            return RuleBasedProvider()
        return HostedProvider(
            api_key=settings.agent_api_key,
            model=settings.agent_hosted_model,
            base_url=settings.agent_hosted_base_url,
            timeout=settings.agent_timeout_seconds,
        )

    if name != "rules":
        logger.warning(
            "unknown agent provider; using rules",
            extra={"requested_provider": name},
        )
    return RuleBasedProvider()


class QueryAgent:
    """Turns a natural-language request into a guarded, structured plan."""

    def __init__(
        self,
        provider: QueryUnderstandingProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_provider(self.settings)
        #: Always available, and used whenever the primary provider fails.
        self.fallback = RuleBasedProvider()

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def understand(self, query: str) -> GuardDecision:
        """Read ``query`` and return a plan that has already been sanitised.

        A provider failure is not an error the caller has to handle: unless
        fallback is explicitly disabled, the rule-based reader takes over, so
        this method always returns a usable decision.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        query = query.strip()
        started = time.perf_counter()
        notes: list[str] = []

        try:
            plan = self.provider.understand(query)
        except (ProviderError, ValueError) as error:
            if not self.settings.agent_fallback_to_rules:
                raise
            logger.warning(
                "provider failed; falling back to rules",
                extra={"provider": self.provider.name, "error": str(error)},
            )
            notes.append(
                f"The '{self.provider.name}' provider failed "
                f"({error}); deterministic keyword understanding was used instead."
            )
            plan = self.fallback.understand(query)

        decision = guard(plan)
        decision.notes = notes + list(decision.notes)

        logger.info(
            "query understood",
            extra={
                "provider": decision.plan.provider,
                "task": decision.plan.task,
                "proposed_tool": decision.plan.tool,
                "confidence": round(decision.plan.confidence, 3),
                "rejected_tools": len(decision.rejected_tools),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return decision


__all__ = ["QueryAgent", "build_provider", "AgentTaskPlan", "GuardDecision"]


def to_task_understanding(plan: AgentTaskPlan, query: str):
    """Adapt a provider's plan to the controller's understanding model.

    The deterministic chain downstream consumes ``TaskUnderstandingResult`` and
    knows nothing about providers. Round-tripping the rule-based provider
    through this function reproduces exactly what the classifier would have
    produced on its own, so enabling the agent layer changes no behaviour until
    a different provider is configured.
    """
    from app.controller.task_understanding.task_understanding import (
        TaskUnderstandingResult,
    )

    return TaskUnderstandingResult(
        original_query=query,
        task_type=plan.task,
        objects=list(plan.objects),
        requested_output=plan.requested_output,
        temporal_requirement=plan.temporal_requirement,
        confidence=plan.confidence,
    )
