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
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from app import USER_AGENT
from app.agents.guard import allowed_tool_ids
from app.agents.schemas import AgentTaskPlan
from app.tools.binding import get_implementation
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
    "sar_analysis": "sar_analysis",
    # Flooding on optical imagery is open water; on radar imagery the
    # pipeline adapts it to SAR analysis once it has seen the files.
    "flood_mapping": "ndwi",
    "optical_sar_fusion": "optical_sar_fusion",
    "image_captioning": "image_captioning",
    "change_vqa": "change_vqa",
}

#: The task a tool answers, for a provider that names a tool but not a task
#: the controller knows.
TOOL_TO_TASK = {
    "ndvi": "ndvi",
    "ndwi": "ndwi",
    "ndbi": "ndbi",
    "change_detection": "change_detection",
    "object_detection": "object_detection",
    "land_cover_classification": "classification",
    "satellite_vqa": "image_analysis",
    "sar_analysis": "sar_analysis",
    "optical_sar_fusion": "optical_sar_fusion",
    "image_captioning": "image_captioning",
    "change_vqa": "change_vqa",
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
    "sar_analysis": "sar_analysis",
    "flood_mapping": "index_computation",
    "optical_sar_fusion": "cross_modal_fusion",
    "image_captioning": "image_captioning",
    "change_vqa": "change_question_answering",
}

#: Tasks answered by the vision-language model rather than computed.
VLM_TASKS = {"image_analysis", "image_captioning", "change_vqa"}

#: A question about change that asks what happened rather than how much or
#: where: that is what a vision model adds to a measured change map. "Where"
#: and "how much" stay with the deterministic engine, which answers them
#: exactly.
CHANGE_QUESTION_PATTERN = re.compile(
    r"^\s*(what|how|is|are|was|were|did|does|do|has|have|why|which)\b(?!\s+much\b)",
    re.IGNORECASE,
)

#: A sentence phrased as a question, which is what visual question answering
#: is for when no measurement matched it.
QUESTION_PATTERN = re.compile(
    r"\?\s*$|^\s*(what|where|which|how|is|are|was|were|does|do|can|could|why|who|when)\b",
    re.IGNORECASE,
)

CLARIFICATION = (
    "The request does not say which analysis to perform. Ask for a specific "
    "measurement, for example vegetation health (NDVI), water (NDWI), built-up "
    "area (NDBI), a land-cover map, how many water bodies there are, flooding "
    "on radar imagery, or a change comparison between two dates."
)


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
        allowed = allowed_tool_ids()
        vqa_ready = "satellite_vqa" in allowed
        if task is None and vqa_ready and QUESTION_PATTERN.search(query):
            # A free-form question no measurement matches is exactly what the
            # vision model is for -- when an operator has switched it on.
            task = "image_analysis"
        if (
            task == "change_detection"
            and "change_vqa" in allowed
            and CHANGE_QUESTION_PATTERN.search(query)
            and not understanding.context.metrics
        ):
            # Measured change, then described: the deterministic change map
            # runs first and the model answers with its numbers in hand.
            task = "change_vqa"

        clarification = None
        if task is None or (task in VLM_TASKS and not vqa_ready):
            # "Analyze this image" names no analysis. Guessing one would be
            # fabrication, so the request is returned for clarification.
            clarification = CLARIFICATION
            if get_implementation("satellite_vqa") is not None and (
                task in VLM_TASKS or QUESTION_PATTERN.search(query)
            ):
                # The capability exists but an operator has not switched it
                # on; saying so beats implying the question was unclear.
                clarification += (
                    " Free-form questions about what an image shows are answered "
                    "by satellite VQA, which is switched off in this deployment."
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
                "No measurement matched the wording, and it is phrased as a "
                "question, so it goes to visual question answering."
                if task == "image_analysis" and understanding.task_type is None
                else f"Matched the query to task '{task}' by keyword."
                if task
                else "No known remote-sensing task matched the wording."
            ),
            locations=list(understanding.context.locations),
            metrics=list(understanding.context.metrics),
        )


PROMPT = """You classify remote-sensing requests. Reply with one JSON object and nothing else.

Allowed "task" values: ndvi (vegetation), ndwi (water), ndbi (built-up land),
change_detection (comparing two dates), classification (land-cover map),
object_detection (counting or listing discrete objects: "how many lakes are
there?", "list every water body"), sar_analysis (radar imagery),
flood_mapping (flooding), optical_sar_fusion (combining an optical and a
radar image), image_captioning (describe the image), change_vqa (a question
about what changed between two images), image_analysis (a yes/no or open
question about what the image shows: "is there a river?", "what kind of area
is this?").
Choose image_analysis when the request asks whether something is visible, and
object_detection only when it asks to count or list objects.
Allowed "tool" values: {tools}
Use null for "task" or "tool" if none applies.

Schema:
{{"task": string|null, "operation": string|null, "tool": string|null,
 "confidence": number 0..1, "parameters": object, "objects": [string],
 "requested_output": string|null,
 "temporal_requirement": "single"|"bi_temporal"|null,
 "locations": [string], "metrics": [string],
 "clarification": string|null, "reasoning": string}}

"locations" lists place names exactly as the request writes them.
"metrics" uses only: area, percentage, count, amount, mean, median, maximum, minimum.
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
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
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
    "TOOL_TO_TASK",
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
                "User-Agent": USER_AGENT,
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
