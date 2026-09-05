"""Application logging.

One place decides the format and level, so no module has to configure logging
for itself and the output stays consistent whether the process is a test run,
``uvicorn``, or a container.

Two rules are enforced here rather than left to callers:

*Nothing secret is logged.* The logger never receives credentials because the
system holds none -- but request bodies and file contents are also deliberately
absent from every call site, so a log file can be shared safely.

*A request is traceable end to end.* Every task carries its ``task_id`` into
the log record, so the understanding, validation, selection and execution lines
for one request can be recovered from an interleaved log.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.config.settings import get_settings

LOGGER_NAME = "satquery"

#: Attributes present on every ``LogRecord``; anything else was attached by a
#: call site via ``extra=`` and is therefore structured context worth emitting.
_STANDARD_ATTRIBUTES = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render each record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ContextFormatter(logging.Formatter):
    """Plain text, with any structured context appended as ``key=value``."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extra = _extra_fields(record)
        if not extra:
            return base
        rendered = " ".join(f"{key}={value}" for key, value in sorted(extra.items()))
        return f"{base} | {rendered}"


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRIBUTES and not key.startswith("_")
    }


def configure_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """Install SatQuery's handler on the application logger.

    Idempotent: calling it twice does not duplicate handlers, which matters
    because the app factory runs once per process but many times per test run.
    """
    settings = get_settings()
    level = (level or settings.log_level).upper()
    json_output = settings.log_json if json_output is None else json_output

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level, logging.INFO))
    # The application logger owns its output; without this, records would also
    # reach the root handler that uvicorn or pytest installs.
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else ContextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    logger.addHandler(handler)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the application logger."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


__all__ = ["configure_logging", "get_logger", "JsonFormatter", "ContextFormatter"]
