"""Tests for satellite VQA: its opt-in gate, what it sends, and what it claims.

The network call is replaced in every test. What is checked is the contract
around it: nothing is sent unless an operator enabled VQA, what is sent is a
real rendering of the scene with the question and its context, and the answer
comes back labelled as a model's reading rather than a measurement.
"""

from __future__ import annotations

import base64
import struct
import zlib

import pytest

from app.config.settings import reset_settings
from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.raster.io import open_raster
from app.tools.vlm import client
from app.tools.raster.render import encode_png, render_preview
from app.tools.vlm.vqa import SatelliteVQATool
from tests.conftest import make_band


@pytest.fixture
def vqa_enabled(monkeypatch):
    monkeypatch.setenv("SATQUERY_VQA_ENABLED", "true")
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    # Keep query understanding offline even though a key is now present.
    monkeypatch.setenv("SATQUERY_AGENT_PROVIDER", "rules")
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def model(monkeypatch):
    """Replace the network call and record what would have been sent."""
    calls = []

    def fake_post(url, payload, api_key, timeout):
        calls.append({"url": url, "payload": payload, "api_key": api_key})
        return {"choices": [{"message": {"content": "Yes, a river crosses the scene."}}]}

    monkeypatch.setattr(client, "post_json", fake_post)
    return calls


def ask(path, tmp_path, question="Is there a river?"):
    return SatelliteVQATool().execute(
        ToolRequest(
            tool_id="satellite_vqa",
            input_references=[path],
            parameters={"question": question},
            output_directory=str(tmp_path / "out"),
        )
    )


def test_vqa_is_off_until_an_operator_enables_it():
    tool = SatelliteVQATool()
    assert tool.available() is False
    reason = tool.unavailable_reason()
    assert "SATQUERY_VQA_ENABLED=true" in reason
    assert "SATQUERY_AGENT_API_KEY" in reason


def test_a_key_alone_does_not_enable_it(monkeypatch):
    monkeypatch.setenv("SATQUERY_AGENT_API_KEY", "test-key-not-real")
    reset_settings()
    try:
        assert SatelliteVQATool().available() is False
    finally:
        reset_settings()


def test_nothing_is_sent_while_it_is_off(sentinel2_scene, tmp_path, model):
    with pytest.raises(ToolExecutionError, match="switched off"):
        ask(sentinel2_scene, tmp_path)
    assert model == []


def test_the_scene_and_question_are_sent_with_their_context(
    vqa_enabled, model, sentinel2_scene, tmp_path
):
    output = ask(sentinel2_scene, tmp_path)

    (call,) = model
    assert call["url"].endswith("/chat/completions")
    assert call["api_key"] == "test-key-not-real"
    content = call["payload"]["messages"][0]["content"]
    prompt = content[0]["text"]
    image = content[1]["image_url"]["url"]

    assert "Question: Is there a river?" in prompt
    assert "true colour" in prompt
    assert "Sensor: sentinel2" in prompt
    assert image.startswith("data:image/png;base64,")
    assert base64.b64decode(image.split(",", 1)[1])[:8] == b"\x89PNG\r\n\x1a\n"

    assert output.data["answer"] == "Yes, a river crosses the scene."
    assert "not a measurement" in output.data["notice"]
    assert output.confidence is None
    assert output.artifacts[0].kind == "image"


def test_an_unusable_reply_is_an_error_not_an_answer(
    vqa_enabled, monkeypatch, sentinel2_scene, tmp_path
):
    monkeypatch.setattr(client, "post_json", lambda *args: {"choices": []})
    with pytest.raises(ToolExecutionError, match="did not contain an answer"):
        ask(sentinel2_scene, tmp_path)


def test_the_key_never_appears_in_an_error(vqa_enabled, monkeypatch):
    import urllib.error

    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(client.urllib.request, "urlopen", refuse)
    with pytest.raises(ToolExecutionError) as error:
        client.post_json("https://example.invalid/v1/chat/completions", {}, "secret-key-123", 5)
    assert "HTTP 401" in str(error.value)
    assert "secret-key-123" not in str(error.value)


def test_a_question_is_required():
    with pytest.raises(ToolExecutionError, match="question is needed"):
        SatelliteVQATool().preflight(ToolRequest(tool_id="satellite_vqa", parameters={}))


# ============================================================
# RENDERING
# ============================================================
def _decode_png(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    position, chunks = 8, {}
    while position < len(data):
        (length,) = struct.unpack(">I", data[position:position + 4])
        tag = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        (crc,) = struct.unpack(">I", data[position + 8 + length:position + 12 + length])
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF
        chunks[tag] = chunks.get(tag, b"") + body
        position += 12 + length
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    return width, height, zlib.decompress(chunks[b"IDAT"])


def test_the_png_encoder_writes_a_valid_file():
    rows = [bytes([255, 0, 0, 0, 255, 0]), bytes([0, 0, 255, 255, 255, 255])]
    width, height, raw = _decode_png(encode_png(2, 2, rows))
    assert (width, height) == (2, 2)
    assert raw == b"\x00" + rows[0] + b"\x00" + rows[1]


def test_optical_scenes_render_in_true_colour_and_are_decimated(raster_factory):
    values = list(range(1, 101))
    path = raster_factory(
        "big.tif",
        [make_band(name, values, 10, 10) for name in ("B2", "B3", "B4", "B8")],
    )
    preview = render_preview(open_raster(path), max_side=5)
    assert preview.kind == "true_colour"
    assert (preview.width, preview.height) == (5, 5)
    assert _decode_png(preview.png)[:2] == (5, 5)


def test_without_blue_the_rendering_is_false_colour_and_says_so(raster_factory):
    path = raster_factory(
        "nirrg.tif", [make_band(name, [1, 2, 3, 4], 2, 2) for name in ("B3", "B4", "B8")]
    )
    preview = render_preview(open_raster(path))
    assert preview.kind == "false_colour"
    assert "vegetation appears bright red" in preview.description


def test_sar_renders_as_labelled_greyscale(raster_factory):
    path = raster_factory(
        "sar.tif",
        [make_band("VV", [-20.0, -10.0, -5.0, -15.0], 2, 2, dtype="float32")],
        sensor="sentinel1",
    )
    preview = render_preview(open_raster(path))
    assert preview.kind == "sar_greyscale"
    assert "not a photograph" in preview.description


def test_cloud_does_not_set_the_stretch_when_the_scene_says_where_it_is(raster_factory):
    # Six ground pixels, four cloud tops ten times brighter, marked in SCL.
    ground, cloud = [500, 600, 700, 800, 900, 1000], [9000] * 4
    scl = [4] * 6 + [9] * 4
    bands = [make_band(name, ground + cloud, 5, 2) for name in ("B2", "B3", "B4")]
    path = raster_factory("cloudy.tif", bands + [make_band("SCL", scl, 5, 2, dtype="uint8")])

    preview = render_preview(open_raster(path))
    # Stretched to the ground, so the ground spans the range and cloud clips white.
    assert all(high <= 1000 for _, high in preview.limits)

    without_scl = raster_factory("cloudy_no_scl.tif", bands)
    assert render_preview(open_raster(without_scl)).limits[0][1] == 9000
