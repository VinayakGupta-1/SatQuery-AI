"""Keeping credentials out of anything a user can read.

Error text travels far: into answers, agent notes, the execution trace and
logs, and from there onto a public results page. Two defences live here:

* :func:`check_key` refuses a malformed key before it is put in a header. A
  key pasted with a line break makes Python's HTTP client raise an error that
  quotes the whole header, key included.
* :func:`redact` scrubs a message of the configured keys and of anything that
  looks like a bearer token or a provider key, whatever raised it.
"""

from __future__ import annotations

import re

from app.config.settings import get_settings

REDACTED = "[redacted]"

#: Bearer headers, and the key formats of the providers this service talks to
#: (Groq, OpenAI-compatible servers, Hugging Face).
_TOKEN_PATTERNS = re.compile(
    r"(?i:bearer)\s+\S+"
    r"|\bgsk_[A-Za-z0-9]{8,}"
    r"|\bsk-[A-Za-z0-9_-]{8,}"
    r"|\bhf_[A-Za-z0-9]{8,}"
)


def malformed_key_problem(key: str, name: str) -> str | None:
    """Why ``key`` cannot be sent in a header, or None when it can."""
    if key and any(char.isspace() or ord(char) < 32 for char in key):
        return (
            f"{name} contains a space or a line break. Set it to the key "
            f"alone, on one line."
        )
    return None


def check_key(key: str, name: str, error: type[Exception]) -> None:
    """Raise ``error`` (never quoting the key) when ``key`` is malformed."""
    problem = malformed_key_problem(key, name)
    if problem:
        raise error(problem)


def redact(message: str) -> str:
    """``message`` with every credential it might contain replaced."""
    settings = get_settings()
    for secret in (settings.agent_api_key, settings.vqa_api_key):
        # A malformed key may appear whole or one line at a time.
        for part in [secret, *secret.split()]:
            if len(part) >= 8:
                message = message.replace(part, REDACTED)
    return _TOKEN_PATTERNS.sub(REDACTED, message)
