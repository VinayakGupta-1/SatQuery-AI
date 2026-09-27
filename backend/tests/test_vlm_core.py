"""Tests for the rest of the vision-language model core: captioning with region
grounding, and change-VQA.

As in ``test_vqa.py`` the network call is replaced in every test. What is
checked is what SatQuery does around the model: the boxes it proposes are
validated and placed on the map, a malformed reply degrades rather than
inventing regions, and a change question is measured before it is described.
"""

from __future__ import annotations

import json

import pytest

from app.agents.agent import QueryAgent
from app.agents.providers import RuleBasedProvider
from app.config.settings import reset_settings
from app.controller.pipeline import SatQueryPipeline
from app.schemas.inputs import ImageInput
from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.raster.inspection import describe_raster
from app.tools.raster.io import open_raster
from app.tools.vlm import client
from app.tools.vlm.captioning import ImageCaptioningTool, ground_regions, parse_reply
from app.tools.vlm.change_vqa import ChangeVQATool
from tests.conftest import make_band

MODEL_IDENTITY = "hosted:qwen/qwen3.8-27b"


@pytest.fixture
def vqa_enabled(monkeypatch):
    monkeypatch.setenv("SATQUERY_VQA_ENABLED", "true")
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "rules")
    reset_settings()
    yield
    reset_settings()


def fake_model(monkeypatch, reply: str):
    """Answer every call with ``reply`` and record what was sent."""
    calls = []

    def post(url, payload, api_key, timeout):
        calls.append(payload)
        return {"choices": [{"message": {"content": reply}}]}

    monkeypatch.setattr(client, "post_json", post)
    return calls


@pytest.fixture
def scene(raster_factory):
    """A 10x10 four-band scene on the shared 10 m UTM grid."""
    values = list(range(500, 600))
    return raster_factory(
        "scene.tif",
        [make_band(name, values, 10, 10) for name in ("B2", "B3", "B4", "B8")],
        metadata_extra={"acquisition_date": "2024-09-18"},
    )


def dated_pair(raster_factory):
    """Two 4x4 optical dates: the left half loses its vegetation."""
    def bands(nir_left):
        nir = [nir_left if col < 2 else 4000 for _row in range(4) for col in range(4)]
        return [
            make_band("B2", [700] * 16, 4, 4),
            make_band("B3", [900] * 16, 4, 4),
            make_band("B4", [800] * 16, 4, 4),
            make_band("B8", nir, 4, 4),
        ]

    before = raster_factory("before.tif", bands(4000), metadata_extra={"acquisition_date": "2023-11-02"})
    after = raster_factory("after.tif", bands(900), metadata_extra={"acquisition_date": "2024-09-18"})
    return before, after


# ============================================================
# READING THE MODEL'S REPLY
# ============================================================
def test_a_json_reply_is_split_into_caption_and_regions():
    caption, regions, notes = parse_reply(
        '{"caption": "A river crosses farmland.", "regions": [{"label": "river", "box": [0, 0, 1, 0.2]}]}'
    )
    assert caption == "A river crosses farmland."
    assert regions == [{"label": "river", "box": [0, 0, 1, 0.2]}]
    assert notes == []


def test_json_wrapped_in_prose_is_still_read():
    caption, regions, _ = parse_reply('Here you go: {"caption": "Fields.", "regions": []} Hope that helps.')
    assert caption == "Fields." and regions == []


def test_a_reply_that_is_not_json_becomes_a_caption_without_regions():
    caption, regions, notes = parse_reply("Mostly farmland with a small town.")
    assert caption == "Mostly farmland with a small town."
    assert regions == []
    assert "no regions were grounded" in notes[0]


def test_json_without_a_caption_is_an_error():
    with pytest.raises(ToolExecutionError, match="no caption"):
        parse_reply('{"regions": []}')


# ============================================================
# GROUNDING THE PROPOSED REGIONS
# ============================================================
def test_a_box_is_placed_on_pixels_map_and_ground(scene):
    (region,), rejected = ground_regions(
        [{"label": "reservoir", "box": [0.2, 0.3, 0.6, 0.9]}], open_raster(scene)
    )
    assert rejected == 0
    assert region["label"] == "reservoir"
    assert region["bbox_pixels"] == [2, 3, 5, 8]
    # 10 m pixels from origin (699960, 2100000), rows going south.
    assert region["bbox"] == [699980.0, 2099910.0, 700020.0, 2099970.0]
    lon, lat = region["centre_lonlat"]
    assert 76.85 < lon < 76.95 and 18.95 < lat < 19.0


def test_per_mille_boxes_are_accepted_as_the_same_box(scene):
    dataset = open_raster(scene)
    fractions, _ = ground_regions([{"label": "a", "box": [0.2, 0.3, 0.6, 0.9]}], dataset)
    per_mille, _ = ground_regions([{"label": "a", "box": [200, 300, 600, 900]}], dataset)
    assert fractions[0]["bbox_pixels"] == per_mille[0]["bbox_pixels"]


def test_malformed_boxes_are_dropped_and_counted(scene):
    regions, rejected = ground_regions(
        [
            {"label": "inverted", "box": [0.5, 0.5, 0.4, 0.9]},
            {"label": "off the scale", "box": [0, 0, 2000, 1]},
            {"label": "three numbers", "box": [0, 0, 1]},
            {"box": [0, 0, 1, 1]},
            {"label": "fine", "box": [0, 0, 1, 1]},
        ],
        open_raster(scene),
    )
    assert [region["label"] for region in regions] == ["fine"]
    assert rejected == 4


def test_the_number_of_regions_is_bounded(scene):
    regions, _ = ground_regions([{"label": str(i), "box": [0, 0, 1, 1]} for i in range(50)], open_raster(scene))
    assert len(regions) == 8


# ============================================================
# THE CAPTIONING TOOL
# ============================================================
def test_captioning_asks_for_json_and_grounds_the_answer(vqa_enabled, monkeypatch, scene, tmp_path):
    calls = fake_model(
        monkeypatch,
        json.dumps({"caption": "Farmland around a reservoir.", "regions": [
            {"label": "reservoir", "box": [0.2, 0.3, 0.6, 0.9]},
            {"label": "nonsense", "box": "everywhere"},
        ]}),
    )
    output = ImageCaptioningTool().execute(
        ToolRequest(tool_id="image_captioning", input_references=[scene], output_directory=str(tmp_path))
    )

    (payload,) = calls
    assert payload["response_format"] == {"type": "json_object"}
    assert "Do not invent place names" in payload["messages"][0]["content"][0]["text"]
    assert output.data["caption"] == "Farmland around a reservoir."
    assert [region["label"] for region in output.data["regions"]] == ["reservoir"]
    assert "1 proposed region(s)" in output.data["notes"][0]
    assert "not measured boundaries" in output.data["notice"]
    assert output.artifacts[0].artifact_id == "caption_preview"


def test_captioning_sends_nothing_while_the_model_is_off(monkeypatch, scene, tmp_path):
    calls = fake_model(monkeypatch, "{}")
    with pytest.raises(ToolExecutionError, match="switched off"):
        ImageCaptioningTool().execute(
            ToolRequest(tool_id="image_captioning", input_references=[scene], output_directory=str(tmp_path))
        )
    assert calls == []


# ============================================================
# CHANGE-VQA: MEASURED, THEN DESCRIBED
# ============================================================
def test_change_is_measured_before_the_model_is_asked(vqa_enabled, monkeypatch, raster_factory, tmp_path):
    calls = fake_model(monkeypatch, "The western half was cleared of vegetation.")
    before, after = dated_pair(raster_factory)

    output = ChangeVQATool().execute(
        ToolRequest(
            tool_id="change_vqa",
            input_references=[after, before],  # out of order on purpose
            parameters={"question": "What happened to the forest?", "index": "ndvi"},
            output_directory=str(tmp_path),
        )
    )

    (payload,) = calls
    content = payload["messages"][0]["content"]
    prompt = content[0]["text"]
    assert len(content) == 3  # the prompt and both dates
    assert "treat these numbers as correct" in prompt
    assert "50.0% of the comparable area changed" in prompt
    assert "Dates: 2023-11-02 (earlier) and 2024-09-18 (later)" in prompt
    assert prompt.rstrip().endswith("Question: What happened to the forest?")

    assert output.data["answer"] == "The western half was cleared of vegetation."
    assert output.data["measured"]["earlier_date"] == "2023-11-02"
    assert output.data["classes"]["decrease"]["fraction"] == pytest.approx(0.5)
    assert output.statistics["changed_fraction"] == pytest.approx(0.5)
    assert "were measured" in output.data["notice"]
    ids = {artifact.artifact_id for artifact in output.artifacts}
    assert {"earlier_preview", "later_preview"} <= ids and len(ids) > 2
    assert any(step["name"].startswith("measure_change.") for step in output.metadata["steps"])


def test_change_vqa_needs_two_images(vqa_enabled, monkeypatch, scene):
    fake_model(monkeypatch, "")
    with pytest.raises(ToolExecutionError, match="exactly two images"):
        ChangeVQATool().execute(
            ToolRequest(tool_id="change_vqa", input_references=[scene], parameters={"question": "What changed?"})
        )


# ============================================================
# THROUGH THE PIPELINE, WITH THE ROUTE AND CONFIDENCE
# ============================================================
def _image(path, image_id="image_1"):
    return ImageInput(id=image_id, path=path, metadata=describe_raster(path))


@pytest.fixture
def pipeline():
    return SatQueryPipeline(agent=QueryAgent(provider=RuleBasedProvider()))


def test_describe_this_image_is_routed_to_the_vlm(vqa_enabled, monkeypatch, pipeline, scene, tmp_path):
    fake_model(monkeypatch, '{"caption": "Farmland.", "regions": []}')
    run = pipeline.run("Describe this image", [_image(scene)], output_directory=str(tmp_path))

    assert run.selection.selected_tool_id == "image_captioning"
    assert run.route == "vlm"
    assert run.status == "success"
    assert run.final.confidence_report.level == "unrated"
    assert run.final.confidence is None


def test_a_what_question_about_two_dates_is_answered_by_the_hybrid_route(
    vqa_enabled, monkeypatch, pipeline, raster_factory, tmp_path
):
    fake_model(monkeypatch, "Vegetation was cleared in the west.")
    before, after = dated_pair(raster_factory)
    run = pipeline.run(
        "What happened to the vegetation between these two images?",
        [_image(before, "image_1"), _image(after, "image_2")],
        output_directory=str(tmp_path),
    )

    assert run.selection.selected_tool_id == "change_vqa"
    assert run.route == "hybrid"
    assert run.status == "success"
    assert "change figures it was given are measured" in run.final.confidence_report.basis


def test_where_and_how_much_stay_with_the_deterministic_engine(
    vqa_enabled, monkeypatch, pipeline, raster_factory, tmp_path
):
    calls = fake_model(monkeypatch, "unused")
    before, after = dated_pair(raster_factory)
    run = pipeline.run(
        "Show where vegetation decreased between these two images",
        [_image(before, "image_1"), _image(after, "image_2")],
        output_directory=str(tmp_path),
    )
    assert run.selection.selected_tool_id == "change_detection"
    assert run.route == "deterministic"
    assert calls == []


def test_a_benchmarked_model_carries_its_measured_accuracy(
    vqa_enabled, monkeypatch, pipeline, scene, tmp_path
):
    report = tmp_path / "benchmark.json"
    report.write_text(json.dumps({
        "model": MODEL_IDENTITY, "dataset": "rsvqa", "samples": 500, "overall_accuracy": 0.72,
    }))
    monkeypatch.setenv("SATQUERY_VQA_BENCHMARK_REPORT", str(report))
    reset_settings()
    fake_model(monkeypatch, '{"caption": "Farmland.", "regions": []}')

    run = pipeline.run("Describe this image", [_image(scene)], output_directory=str(tmp_path / "out"))

    confidence = run.final.confidence_report
    factor = next(f for f in confidence.factors if f.name == "model_accuracy")
    assert factor.score == pytest.approx(0.72)
    assert "500 rsvqa questions" in factor.detail
    assert confidence.level != "unrated"
    assert confidence.score <= 0.72


# ============================================================
# THE TRANSPORT: WHO WE SAY WE ARE, AND WAITING OUT RATE LIMITS
# ============================================================
class _Reply:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, retry_after=None):
    import urllib.error
    from email.message import Message

    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.invalid", code, "error", headers, None)


def test_every_request_names_satquery_as_its_user_agent(monkeypatch):
    # Groq sits behind Cloudflare, which refuses the default "Python-urllib"
    # agent with HTTP 403 before the key is even checked.
    seen = []

    def urlopen(request, timeout):
        seen.append(request.get_header("User-agent"))
        return _Reply({"ok": True})

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    assert client.post_json("https://example.invalid/v1/chat/completions", {}, "k", 5) == {"ok": True}
    assert seen[0].startswith("SatQuery/")


def test_a_rate_limit_is_waited_out_not_failed(monkeypatch):
    replies = [_http_error(429, "1.5"), _http_error(503), _Reply({"ok": True})]
    waits = []

    def urlopen(request, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(client.time, "sleep", waits.append)

    assert client.post_json("https://example.invalid", {}, "k", 5) == {"ok": True}
    assert waits == [1.5, 4.0]  # the server's Retry-After, then backoff


def test_a_short_limit_that_never_lifts_fails_after_bounded_waits(monkeypatch):
    waits = []

    def urlopen(request, timeout):
        raise _http_error(429, "20")

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(client.time, "sleep", waits.append)

    with pytest.raises(client.RateLimited, match="HTTP 429.*about 20 seconds"):
        client.post_json("https://example.invalid", {}, "k", 5)
    assert waits == [20.0, 20.0, 20.0]  # only MAX_ATTEMPTS - 1 of them


def test_a_daily_quota_is_reported_at_once_not_waited_on(monkeypatch):
    # Groq's free tier answers an exhausted daily token budget with a 429
    # asking for minutes; waiting would only delay the same refusal.
    waits = []

    def urlopen(request, timeout):
        raise _http_error(429, "400")

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(client.time, "sleep", waits.append)

    with pytest.raises(client.RateLimited, match="quota has been reached.*about 7 minutes") as error:
        client.post_json("https://example.invalid", {}, "k", 5)
    assert error.value.retry_after == 400.0
    assert waits == []


def test_an_outage_is_not_blamed_on_the_model_name(monkeypatch):
    def urlopen(request, timeout):
        raise _http_error(503, "3600")

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    with pytest.raises(ToolExecutionError, match="temporarily unavailable"):
        client.post_json("https://example.invalid", {}, "k", 5)


@pytest.mark.parametrize("seconds, words", [(45, "45 seconds"), (400, "7 minutes"), (7200, "2.0 hours")])
def test_waits_are_described_in_words(seconds, words):
    assert client.describe_wait(seconds) == words


def test_a_rejected_key_is_named_and_not_retried(monkeypatch):
    calls = []

    def urlopen(request, timeout):
        calls.append(1)
        raise _http_error(401)

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    with pytest.raises(ToolExecutionError, match="SATQUERY_AGENT_API_KEY is a current key"):
        client.post_json("https://example.invalid", {}, "k", 5)
    assert calls == [1]


def test_query_understanding_also_sends_the_user_agent(monkeypatch):
    from app.agents import providers

    seen = []

    def urlopen(request, timeout):
        seen.append(request.get_header("User-agent"))
        return _Reply({"choices": [{"message": {"content": json.dumps({"task": "ndvi", "tool": "ndvi"})}}]})

    monkeypatch.setattr(providers.urllib.request, "urlopen", urlopen)
    plan = providers.HostedProvider("k", "m", "https://example.invalid/v1").understand("Calculate NDVI")
    assert plan.task == "ndvi"
    assert seen[0].startswith("SatQuery/")


# ============================================================
# WHICH KEY GOES WHERE
# ============================================================
@pytest.fixture
def settings_env(monkeypatch):
    def apply(**values):
        for name, value in values.items():
            monkeypatch.setenv(f"SATQUERY_{name}", value)
        reset_settings()
        from app.config.settings import get_settings

        return get_settings()

    yield apply
    reset_settings()


def test_the_hosted_default_uses_the_understanding_key(settings_env):
    settings = settings_env(VQA_ENABLED="true", AGENT_API_KEY="groq-key")
    assert settings.vqa_available
    assert settings.resolved_vqa_api_key == "groq-key"


def test_a_self_hosted_model_is_never_sent_the_groq_key(settings_env):
    settings = settings_env(
        VQA_ENABLED="true", AGENT_API_KEY="groq-key", VQA_BASE_URL="http://127.0.0.1:8001/v1"
    )
    assert settings.vqa_available  # a self-hosted endpoint needs no key
    assert settings.resolved_vqa_api_key == ""


def test_a_self_hosted_model_can_have_its_own_key(settings_env):
    settings = settings_env(
        VQA_ENABLED="true", VQA_BASE_URL="https://vlm.example/v1", VQA_API_KEY="own-key"
    )
    assert settings.vqa_available
    assert settings.resolved_vqa_api_key == "own-key"


def test_the_hosted_default_without_a_key_stays_off(settings_env):
    settings = settings_env(VQA_ENABLED="true")
    assert not settings.vqa_available
    from app.tools.vlm.core import vlm_unavailable_reason

    assert "SATQUERY_AGENT_API_KEY" in vlm_unavailable_reason()
