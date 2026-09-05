"""Tests for configuration, logging and the registry metadata they expose."""

from __future__ import annotations

import json
import logging

import pytest

from app.config.logging_config import (
    ContextFormatter,
    JsonFormatter,
    configure_logging,
    get_logger,
)
from app.config.settings import Settings, get_settings, reset_settings
from app.registry.registry import (
    OutputType,
    get_all_tools,
    get_tool,
    get_tool_version,
)


# ============================================================
# CONFIGURATION
# ============================================================
def test_the_defaults_require_no_configuration_at_all():
    """The backend must run with nothing set, and cost nothing to run."""
    settings = Settings()

    assert settings.agent_provider == "auto"
    # With no key configured, "auto" is the deterministic offline reader.
    assert settings.resolved_agent_provider == "rules"
    assert settings.has_agent_api_key is False
    assert settings.agent_fallback_to_rules is True
    assert settings.max_images_per_task > 0
    assert settings.allowed_extensions


def test_no_credential_is_present_unless_the_operator_supplies_one():
    """The key defaults to empty, so nothing is ever contacted by default."""
    assert Settings().agent_api_key == ""


def test_a_key_switches_the_hosted_model_on(monkeypatch):
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    reset_settings()
    try:
        assert get_settings().resolved_agent_provider == "hosted"
    finally:
        reset_settings()


def test_removing_the_key_switches_it_back_off(monkeypatch):
    """The LLM is an enhancement that can be withdrawn, not a dependency."""
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    reset_settings()
    assert get_settings().resolved_agent_provider == "hosted"

    monkeypatch.delenv("SATQUERY_AGENT_API_KEY")
    reset_settings()
    try:
        assert get_settings().resolved_agent_provider == "rules"
    finally:
        reset_settings()


def test_an_explicit_provider_overrides_the_key_based_default(monkeypatch):
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "rules")
    reset_settings()
    try:
        assert get_settings().resolved_agent_provider == "rules"
    finally:
        reset_settings()


def test_the_hosted_provider_never_renders_its_key(monkeypatch):
    """A key must not reach a log line, a traceback or a debugger."""
    from app.agents.providers import HostedProvider

    provider = HostedProvider(
        api_key="super-secret-key", model="m", base_url="https://example.invalid/v1"
    )
    assert "super-secret-key" not in repr(provider)
    assert "super-secret-key" not in str(provider.__dict__.get("model", ""))


def test_forcing_the_hosted_provider_without_a_key_falls_back(monkeypatch):
    """Misconfiguration degrades understanding; it does not break the service."""
    from app.agents.agent import build_provider

    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "hosted")
    monkeypatch.delenv("SATQUERY_AGENT_API_KEY", raising=False)
    reset_settings()
    try:
        assert build_provider(get_settings()).name == "rules"
    finally:
        reset_settings()


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
     ("0", False), ("false", False), ("no", False), ("nonsense", False)],
)
def test_boolean_environment_values_are_parsed(monkeypatch, raw, expected):
    monkeypatch.setenv("SATQUERY_LOG_JSON", raw)
    reset_settings()
    try:
        assert get_settings().log_json is expected
    finally:
        reset_settings()


def test_a_malformed_integer_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SATQUERY_MAX_IMAGES_PER_TASK", "not-a-number")
    reset_settings()
    try:
        assert get_settings().max_images_per_task == 8
    finally:
        reset_settings()


def test_the_agent_provider_is_normalised(monkeypatch):
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "  OLLAMA  ")
    reset_settings()
    try:
        assert get_settings().agent_provider == "ollama"
    finally:
        reset_settings()


# ============================================================
# REGISTRY METADATA
# ============================================================
def test_every_tool_declares_a_version_and_an_output_type():
    for tool in get_all_tools():
        assert tool.version, f"{tool.tool_id} has no version"
        assert tool.version.count(".") == 2, f"{tool.tool_id}: {tool.version}"
        assert isinstance(tool.output_type, OutputType)


def test_the_version_of_a_tool_can_be_looked_up():
    assert get_tool_version("ndvi") == get_tool("ndvi").version
    assert get_tool_version("no_such_tool") is None


def test_output_types_match_what_the_tools_actually_produce():
    assert get_tool("ndvi").output_type is OutputType.RASTER_INDEX
    assert get_tool("change_detection").output_type is OutputType.CHANGE_MAP
    assert get_tool("object_detection").output_type is OutputType.DETECTIONS


# ============================================================
# LOGGING
# ============================================================
def _record(**extra):
    record = logging.LogRecord(
        "satquery.test", logging.INFO, "path.py", 10, "task complete", None, None
    )
    record.__dict__.update(extra)
    return record


def test_json_logging_emits_one_object_per_line_with_context():
    line = JsonFormatter().format(_record(task_id="task_1", tool="ndvi"))
    payload = json.loads(line)

    assert payload["message"] == "task complete"
    assert payload["level"] == "INFO"
    assert payload["task_id"] == "task_1"
    assert payload["tool"] == "ndvi"


def test_text_logging_appends_context_as_key_values():
    line = ContextFormatter("%(message)s").format(_record(task_id="task_1"))
    assert line == "task complete | task_id=task_1"


def test_a_record_without_context_is_left_alone():
    assert ContextFormatter("%(message)s").format(_record()) == "task complete"


def test_configuring_logging_twice_does_not_duplicate_handlers():
    configure_logging()
    first = len(logging.getLogger("satquery").handlers)
    configure_logging()

    assert len(logging.getLogger("satquery").handlers) == first == 1


def test_the_application_logger_does_not_propagate_to_the_root():
    """Otherwise every line would be emitted twice under uvicorn."""
    configure_logging()
    assert logging.getLogger("satquery").propagate is False


def test_child_loggers_are_namespaced():
    assert get_logger("pipeline").name == "satquery.pipeline"
    assert get_logger().name == "satquery"
