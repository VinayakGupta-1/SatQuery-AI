"""Credentials never reach an answer, a note, the trace or an error response.

The incident these guard against: a Groq key pasted into a deployment with the
next line of ``.env`` attached. Python's HTTP client then refused the header
with an error quoting it, and that error became the public answer.
"""

from __future__ import annotations

import io
import json
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.agents.providers import HostedProvider, ProviderError
from app.api.store import task_store
from app.config.secrets import check_key, redact
from app.config.settings import reset_settings
from app.main import create_app
from app.tools.base import ToolExecutionError
from app.tools.vlm import client

KEY = "gsk_" + "Ab3" * 16
PASTED = KEY + "\nSATQUERY_VQA_ENABLED=true"


@pytest.fixture
def malformed_key(monkeypatch, tmp_path):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", PASTED)
    monkeypatch.setenv("SATQUERY_VQA_ENABLED", "true")
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "hosted")

    def no_network(*args, **kwargs):
        raise AssertionError("a malformed key must be refused before any request")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    reset_settings()
    task_store.clear()
    yield
    task_store.clear()
    reset_settings()


def test_a_malformed_key_is_refused_without_quoting_it():
    with pytest.raises(ToolExecutionError) as caught:
        check_key(PASTED, "SATQUERY_AGENT_API_KEY", ToolExecutionError)
    assert "line break" in str(caught.value)
    assert KEY not in str(caught.value)
    check_key(KEY, "SATQUERY_AGENT_API_KEY", ToolExecutionError)  # a clean key passes


def test_the_vision_client_refuses_before_sending(malformed_key):
    with pytest.raises(ToolExecutionError) as caught:
        client.post_json("https://api.groq.com/x", {}, PASTED, timeout=5)
    assert KEY not in str(caught.value)


def test_the_understanding_provider_refuses_before_sending(malformed_key):
    provider = HostedProvider(api_key=PASTED, model="m", base_url="https://api.groq.com")
    with pytest.raises(ProviderError) as caught:
        provider.understand("How healthy is the vegetation?")
    assert KEY not in str(caught.value)


def test_redact_removes_configured_keys_and_token_shapes(malformed_key):
    message = f"Invalid header value b'Bearer {PASTED}' and hf_{'x' * 20} and sk-{'y' * 20}"
    cleaned = redact(message)
    assert KEY not in cleaned
    assert "hf_" not in cleaned and "sk-" not in cleaned
    assert "[redacted]" in cleaned


def test_no_part_of_the_response_carries_the_key(malformed_key, sentinel2_scene):
    with open(sentinel2_scene, "rb") as handle:
        scene = handle.read()

    with TestClient(create_app()) as api:
        response = api.post(
            "/api/tasks",
            data={"query": "Describe this image"},
            files=[("files", ("scene.tif", io.BytesIO(scene), "image/tiff"))],
        )
        assert "task_id" in response.json(), response.json()
        stored = api.get(f"/api/tasks/{response.json()['task_id']}").text

    body = json.dumps(response.json())
    for text in (body, stored):
        assert KEY not in text
        assert "Bearer" not in text
    assert "line break" in body
