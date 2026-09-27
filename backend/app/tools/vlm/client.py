"""The vision-language model behind the VLM core -- and the only network call
it makes.

One interface, two transports:

``hosted``
    Any OpenAI-compatible chat-completions endpoint: Groq by default, or a
    model you fine-tuned and serve yourself with vLLM or TGI. Images travel as
    base64 data URLs in the request. The key travels only in the
    ``Authorization`` header and never appears in an error message.

``ollama``
    A vision model running on this machine (``llama3.2-vision``, ``qwen2.5vl``,
    or a fine-tuned model imported into Ollama). Nothing leaves the machine.

Which model answers is configuration, not code: swapping in a model
fine-tuned on remote-sensing data -- BigEarthNet, RSVQA -- changes
``SATQUERY_VQA_MODEL`` and nothing else. Tests replace :func:`post_json`, so
no test reaches the network.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any

from app import USER_AGENT
from app.config.settings import Settings, get_settings
from app.tools.base import ToolExecutionError

#: Rate-limited or briefly unavailable: worth waiting for, a few times.
RETRYABLE_STATUS = {429, 503}
MAX_ATTEMPTS = 4
#: Never wait longer than this for one retry, whatever the server asks.
MAX_WAIT_SECONDS = 30.0


def _retry_after(error: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait before retrying: the server's ``Retry-After``, else backoff."""
    header = error.headers.get("Retry-After") if error.headers else None
    try:
        wait = float(header) if header is not None else 2.0 ** attempt
    except ValueError:
        wait = 2.0 ** attempt
    return min(max(wait, 0.0), MAX_WAIT_SECONDS)


def post_json(url: str, payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the decoded JSON response.

    A rate limit (429) or a brief outage (503) is retried a bounded number of
    times, so a free-tier limit slows a burst of requests down instead of
    failing some of them.
    """
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                time.sleep(_retry_after(error, attempt))
                continue
            # The body can echo the request, so it is deliberately not relayed.
            hint = (
                "Check SATQUERY_AGENT_API_KEY is a current key for this endpoint."
                if error.code in {401, 403}
                else "Check SATQUERY_VQA_MODEL names a vision-capable model on this endpoint."
            )
            raise ToolExecutionError(
                f"The vision model rejected the request (HTTP {error.code}). {hint}"
            ) from None
        except (urllib.error.URLError, OSError) as error:
            raise ToolExecutionError(f"The vision model could not be reached: {error}") from None
        except json.JSONDecodeError as error:
            raise ToolExecutionError(f"The vision model returned invalid JSON: {error}") from None
    raise AssertionError("unreachable: the last attempt either returns or raises")


def image_mime(data: bytes) -> str:
    """The MIME type of an encoded image, from its magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ToolExecutionError("The vision model can only be shown PNG, JPEG or WebP images.")


class VisionLanguageModel:
    """Sends a prompt and pictures to the configured vision model."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def provider(self) -> str:
        return self.settings.vqa_provider

    @property
    def model(self) -> str:
        return self.settings.resolved_vqa_model

    @property
    def identity(self) -> str:
        """``provider:model``, the key benchmark results are recorded under."""
        return f"{self.provider}:{self.model}"

    def complete(
        self,
        prompt: str,
        images: list[bytes],
        json_mode: bool = False,
        max_tokens: int = 400,
    ) -> str:
        """Return the model's reply to ``prompt`` about ``images``."""
        if self.provider == "ollama":
            return self._ollama(prompt, images, json_mode)
        return self._hosted(prompt, images, json_mode, max_tokens)

    def _hosted(self, prompt: str, images: list[bytes], json_mode: bool, max_tokens: int) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            encoded = base64.b64encode(image).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{image_mime(image)};base64,{encoded}"}}
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = post_json(
            f"{self.settings.resolved_vqa_base_url}/chat/completions",
            payload,
            self.settings.resolved_vqa_api_key,
            self.settings.vqa_timeout_seconds,
        )
        try:
            content_out = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ToolExecutionError(
                "The vision model's response did not contain an answer."
            ) from error
        return _text(content_out)

    def _ollama(self, prompt: str, images: list[bytes], json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(image).decode("ascii") for image in images],
                }
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if json_mode:
            payload["format"] = "json"
        response = post_json(
            f"{self.settings.resolved_vqa_base_url}/api/chat",
            payload,
            "",
            self.settings.vqa_timeout_seconds,
        )
        try:
            content_out = response["message"]["content"]
        except (KeyError, TypeError) as error:
            raise ToolExecutionError(
                "The local vision model's response did not contain an answer."
            ) from error
        return _text(content_out)


def _text(content: Any) -> str:
    if isinstance(content, list):
        # Some endpoints return content as typed parts.
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ToolExecutionError("The vision model returned an empty answer.")
    return content.strip()


__all__ = ["VisionLanguageModel", "image_mime", "post_json"]
