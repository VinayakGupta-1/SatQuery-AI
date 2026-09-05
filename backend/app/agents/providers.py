"""Query-understanding providers.

A provider turns a sentence into an :class:`AgentTaskPlan`. Three exist:

:class:`RuleBasedProvider`
    The deterministic keyword reader. No network, no model, no key, no cost.
    It cannot fail, and it is what runs when nothing else is configured.

:class:`OllamaProvider`
    A locally hosted open-weights model, reached over ``localhost``. Free and
    offline, but the user has to run Ollama themselves.

:class:`HostedProvider`
    Any OpenAI-compatible chat-completions endpoint, gated on an API key.

The provider is chosen by configuration, and the default (``auto``) selects
the hosted model only when a key is actually present. Remove the key and the
system falls back to the rule engine rather than failing -- so the LLM is an
enhancement that can be switched off, never a dependency.

No vendor is hardcoded. The hosted adapter speaks the protocol that Groq,
OpenRouter and Google AI Studio all implement, each of which issues free-tier
keys, so enabling a model never obliges anyone to open a paid account.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from app.agents.guard import allowed_tool_ids
from app.agents.schemas import AgentTaskPlan
from app.config.logging_config import get_logger
from app.controller.task_classification.task_classification import TaskClassifier
from app.controller.task_understanding.task_understanding import TaskUnderstanding

logger = get_logger("agent")

#: Maps an understood task to the tool that implements it. Only tools that are
#: actually bound appear; the guard re-checks anyway.
TASK_TO_TOOL = {
    "ndvi": "ndvi",
    "ndwi": "ndwi",
    "ndbi": "ndbi",
    "change_detection": "change_detection",
    "object_detection": "object_detection",
    "classification": "land_cover_classification",
    "segmentation": "land_cover_classification",
    "image_analysis": "satellite_vqa",
}

#: Maps an understood task to the broad operation family.
TASK_TO_OPERATION = {
    "ndvi": "index_computation",
    "ndwi": "index_computation",
    "ndbi": "index_computation",
    "change_detection": "temporal_analysis",
    "object_detection": "object_detection",
    "classification": "scene_classification",
    "segmentation": "segmentation",
    "image_analysis": "scene_understanding",
}


class ProviderError(Exception):
    """A provider could not produce a usable plan."""


class QueryUnderstandingProvider(ABC):
    """The contract every understanding backend implements."""

    name: str = "provider"

    @abstractmethod
    def understand(self, query: str) -> AgentTaskPlan:
        """Return a structured reading of ``query``."""

    def available(self) -> bool:
        """Return whether this provider can currently be used."""
        return True


class RuleBasedProvider(QueryUnderstandingProvider):
    """Deterministic keyword understanding. Always available, always free."""

    name = "rules"

    def __init__(self) -> None:
        self._understanding = TaskUnderstanding()
        self._classifier = TaskClassifier()

    def understand(self, query: str) -> AgentTaskPlan:
        understanding = self._understanding.understand(query)
        classification = self._classifier.classify(understanding)

        task = understanding.task_type
        clarification = None
        if task is None or task == "image_analysis":
            # "Analyze this image" names no analysis. Guessing one would be
            # fabrication, so the request is returned for clarification.
            clarification = (
                "The request does not say which analysis to perform. "
                "Ask for a specific measurement, for example vegetation "
                "(NDVI), water (NDWI), built-up area (NDBI), or a change "
                "comparison between two dates."
            )

        return AgentTaskPlan(
            task=task,
            operation=TASK_TO_OPERATION.get(task or "", classification.task_category),
            tool=TASK_TO_TOOL.get(task or ""),
            confidence=understanding.confidence,
            required_inputs=["raster"],
            objects=list(understanding.objects),
            requested_output=understanding.requested_output,
            temporal_requirement=understanding.temporal_requirement,
            clarification=clarification,
            provider=self.name,
            reasoning=(
                f"Matched the query to task '{task}' by keyword."
                if task
                else "No known remote-sensing task matched the wording."
            ),
        )


PROMPT = """You classify remote-sensing requests. Reply with one JSON object and nothing else.

Allowed "tool" values: {tools}
Use null for "tool" if none applies.

Schema:
{{"task": string|null, "operation": string|null, "tool": string|null,
 "confidence": number 0..1, "parameters": object, "objects": [string],
 "requested_output": string|null,
 "temporal_requirement": "single"|"bi_temporal"|null,
 "clarification": string|null, "reasoning": string}}

Set "clarification" when the request does not say which analysis to run.

Request: {query}"""


class OllamaProvider(QueryUnderstandingProvider):
    """Understanding via a locally running Ollama server.

    Free and offline -- the request never leaves ``localhost``. The response is
    parsed as JSON and validated into :class:`AgentTaskPlan`; anything else is
    a :class:`ProviderError`, so malformed model output can never propagate.
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        timeout: int = 30,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        """Return whether the local Ollama server answers."""
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed localhost URL
                f"{self.base_url}/api/tags", timeout=min(self.timeout, 5)
            ) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def understand(self, query: str) -> AgentTaskPlan:
        prompt = PROMPT.format(tools=", ".join(allowed_tool_ids()), query=query)
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                # Ask the runtime itself to constrain the output to JSON, so a
                # chatty model cannot wrap the object in prose.
                "format": "json",
                "options": {"temperature": 0},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as error:
            raise ProviderError(f"The local model could not be reached: {error}") from error
        except json.JSONDecodeError as error:
            raise ProviderError(f"The local model returned invalid JSON: {error}") from error

        return self._parse(body.get("response"), query)

    def _parse(self, raw: Any, query: str) -> AgentTaskPlan:
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError("The local model returned an empty response.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderError(
                f"The local model did not return a JSON object: {error}"
            ) from error
        if not isinstance(parsed, dict):
            raise ProviderError("The local model returned JSON that is not an object.")

        parsed.pop("provider", None)
        try:
            plan = AgentTaskPlan(**parsed, provider=self.name)
        except Exception as error:  # pydantic ValidationError and friends
            raise ProviderError(
                f"The local model's output did not match the required schema: {error}"
            ) from error

        logger.debug("local model produced a plan", extra={"task": plan.task})
        return plan


__all__ = [
    "HostedProvider",
    "OllamaProvider",
    "ProviderError",
    "QueryUnderstandingProvider",
    "RuleBasedProvider",
    "TASK_TO_OPERATION",
    "TASK_TO_TOOL",
]


class HostedProvider(QueryUnderstandingProvider):
    """Understanding via an OpenAI-compatible chat-completions endpoint.

    Deliberately generic rather than vendor-specific. Groq, OpenRouter and
    Google AI Studio all speak this protocol and all issue keys with a free
    tier that needs no payment details, so one adapter covers them and the
    project never has to depend on a paid account.

    The key is read from configuration, sent only in the ``Authorization``
    header, and never logged, echoed or included in an error message.
    """

    name = "hosted"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int = 30,
    ) -> None:
        if not api_key:
            raise ProviderError(
                "The hosted provider needs an API key. Set SATQUERY_AGENT_API_KEY, "
                "or leave it unset to use the rule-based reader."
            )
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:
        """Never render the key, even in a traceback or a debugger."""
        return f"HostedProvider(model={self.model!r}, base_url={self.base_url!r})"

    def available(self) -> bool:
        return bool(self._api_key)

    def understand(self, query: str) -> AgentTaskPlan:
        prompt = PROMPT.format(tools=", ".join(allowed_tool_ids()), query=query)
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                # Ask the endpoint to constrain the reply to a JSON object, so
                # a chatty model cannot wrap it in prose.
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            # The status is useful; the response body may echo the request,
            # so it is deliberately not included.
            raise ProviderError(
                f"The hosted model rejected the request (HTTP {error.code})."
            ) from None
        except (urllib.error.URLError, OSError) as error:
            raise ProviderError(f"The hosted model could not be reached: {error}") from None
        except json.JSONDecodeError as error:
            raise ProviderError(f"The hosted model returned invalid JSON: {error}") from None

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "The hosted model's response did not contain a message."
            ) from error

        return self._parse(content)

    def _parse(self, raw: Any) -> AgentTaskPlan:
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError("The hosted model returned an empty response.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderError(
                f"The hosted model did not return a JSON object: {error}"
            ) from None
        if not isinstance(parsed, dict):
            raise ProviderError("The hosted model returned JSON that is not an object.")

        parsed.pop("provider", None)
        try:
            return AgentTaskPlan(**parsed, provider=self.name)
        except Exception as error:
            raise ProviderError(
                f"The hosted model's output did not match the required schema: {error}"
            ) from None
