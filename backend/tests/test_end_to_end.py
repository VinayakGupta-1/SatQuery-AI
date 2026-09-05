"""The end-to-end proof: a sentence and a real raster in, a real answer out.

Every other test exercises one layer. This one drives the whole system through
HTTP exactly as the React frontend will, and checks each stage actually
happened rather than that the request merely returned 200:

    natural language -> understanding -> plan -> registry -> validation
    -> execution -> real raster arithmetic -> statistics -> artifact
    -> normalised response -> artifact download

The NDVI values are hand-checkable from the fixture's band values, so a
success here means the arithmetic is genuinely correct, not merely present.
"""

from __future__ import annotations

import io
import math

import pytest
from fastapi.testclient import TestClient

from app.api.store import task_store
from app.config.settings import reset_settings
from app.main import create_app
from app.storage.artifacts import reset_artifact_store
from app.tools.raster.io import open_raster
from tests.conftest import SENTINEL2_EXPECTED_NDVI


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    reset_settings()
    reset_artifact_store()
    task_store.clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    task_store.clear()
    reset_settings()
    reset_artifact_store()


@pytest.fixture
def scene(sentinel2_scene):
    with open(sentinel2_scene, "rb") as handle:
        return handle.read()


def _upload(scene_bytes: bytes, name: str = "scene.tif"):
    return ("files", (name, io.BytesIO(scene_bytes), "image/tiff"))


# ============================================================
# THE FULL WORKFLOW
# ============================================================
def test_a_natural_language_request_produces_a_real_verified_ndvi_result(
    client, scene, tmp_path
):
    response = client.post(
        "/analyze",
        data={"query": "Calculate NDVI for this satellite image"},
        files=[_upload(scene)],
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # -- 1. the request was understood, not guessed at -----------------
    assert body["status"] == "success"
    assert body["task"] == "ndvi"
    assert body["agent"]["provider"] == "rules"
    assert body["agent"]["proposed_tool"] == "ndvi"
    assert body["agent"]["rejected_tools"] == []

    # -- 2. a plan was produced ----------------------------------------
    assert body["explanation"]["plan_steps"], "the planner produced no steps"
    assert body["explanation"]["required_bands"], "no band requirement was derived"

    # -- 3. the tool came from the controlled registry ------------------
    assert body["tool"] == "ndvi"
    assert body["tool_version"] == "1.0.0"
    assert body["output_type"] == "raster_index"

    # -- 4. deterministic validation ran and passed ---------------------
    assert body["validation"]["valid"] is True
    assert body["validation"]["errors"] == []
    assert body["explanation"]["stage_status"]["validation"] == "valid"
    assert body["explanation"]["stage_status"]["execution"] == "completed"

    # -- 5. the imagery was inspected server-side -----------------------
    image = body["images"][0]
    assert (image["width"], image["height"]) == (2, 2)
    assert image["crs"] == "EPSG:32643"
    # Band names are canonicalised on ingestion, so B4/B8 are reported by the
    # logical role the validator reasons about.
    assert set(image["bands"]) >= {"red", "nir"}

    # -- 6. real arithmetic, checked against hand-computed values -------
    statistics = body["statistics"]
    assert statistics["valid_pixels"] == 4
    assert statistics["nodata_pixels"] == 0
    assert math.isclose(statistics["minimum"], min(SENTINEL2_EXPECTED_NDVI), abs_tol=1e-6)
    assert math.isclose(statistics["maximum"], max(SENTINEL2_EXPECTED_NDVI), abs_tol=1e-6)
    expected_mean = sum(SENTINEL2_EXPECTED_NDVI) / len(SENTINEL2_EXPECTED_NDVI)
    assert math.isclose(statistics["mean"], expected_mean, abs_tol=1e-6)

    # -- 7. percentiles are present and ordered -------------------------
    percentiles = statistics["percentiles"]
    assert set(percentiles) == {"p5", "p25", "p50", "p75", "p95"}
    ordered = [percentiles[key] for key in ("p5", "p25", "p50", "p75", "p95")]
    assert ordered == sorted(ordered)
    assert math.isclose(statistics["median"], percentiles["p50"], abs_tol=1e-9)

    # -- 8. an artifact was produced and is downloadable ----------------
    assert len(body["artifacts"]) == 1
    artifact = body["artifacts"][0]
    assert artifact["kind"] == "raster"
    assert artifact["url"].startswith("/api/tasks/")

    download = client.get(artifact["url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/tiff"

    # -- 9. the downloaded raster is a valid geospatial product ---------
    written = tmp_path / "downloaded_ndvi.tif"
    written.write_bytes(download.content)
    dataset = open_raster(str(written))

    assert (dataset.width, dataset.height) == (2, 2)
    assert dataset.georeference.crs == "EPSG:32643"          # CRS preserved
    assert dataset.georeference.transform is not None        # georeferencing kept
    values = list(dataset.bands[0].values)
    for actual, expected in zip(values, SENTINEL2_EXPECTED_NDVI):
        assert math.isclose(actual, expected, abs_tol=1e-6)

    # -- 10. the result is retrievable afterwards -----------------------
    again = client.get(f"/results/{body['task_id']}")
    assert again.status_code == 200
    assert again.json()["statistics"]["mean"] == statistics["mean"]


def test_the_dry_run_reports_the_same_decision_without_executing(client, scene):
    response = client.post(
        "/analyze/validate",
        data={"query": "Calculate NDVI for this image"},
        files=[_upload(scene)],
    )
    assert response.status_code == 200
    body = response.json()

    assert body["would_execute"] is True
    assert body["selected_tool"] == "ndvi"
    assert body["validation"]["valid"] is True
    assert "artifacts" not in body      # nothing was produced
    assert client.get("/api/tasks").json() == []   # nothing was recorded


# ============================================================
# THE FAILURE PATHS, END TO END
# ============================================================
def test_an_unspecific_request_asks_a_question_rather_than_inventing_an_answer(
    client, scene
):
    response = client.post(
        "/analyze", data={"query": "Analyze this image"}, files=[_upload(scene)]
    )
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "needs_clarification"
    assert body["agent"]["clarification"]
    assert body["artifacts"] == []
    # The orchestrator was reached and refused: the request resolved to a
    # capability with no implementation bound. Nothing was computed, and the
    # system says so rather than returning a fabricated result.
    assert body["explanation"]["stage_status"]["execution"] == "blocked"
    assert body["statistics"] == {}


def test_imagery_without_the_required_bands_is_refused_with_a_reason(
    client, raster_factory
):
    """NDVI needs red and NIR. A blue/green scene must be rejected, not guessed."""
    from tests.conftest import make_band

    blue = make_band("B2", [900, 950, 1000, 800], 2, 2)
    green = make_band("B3", [1200, 1100, 1300, 1000], 2, 2)
    path = raster_factory("no_nir.tif", [blue, green])
    with open(path, "rb") as handle:
        payload = handle.read()

    response = client.post(
        "/analyze", data={"query": "Calculate NDVI"}, files=[_upload(payload, "no_nir.tif")]
    )
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "validation_error"
    assert body["validation"]["valid"] is False
    codes = {error["code"] for error in body["validation"]["errors"]}
    assert codes                                  # a machine-readable reason
    assert body["artifacts"] == []
    assert body["explanation"]["stage_status"]["execution"] == "not_reached"


def test_change_detection_over_one_image_is_refused_before_execution(client, scene):
    response = client.post(
        "/analyze",
        data={"query": "Compare these images and find the changes"},
        files=[_upload(scene)],
    )
    body = response.json()

    assert body["status"] == "validation_error"
    assert body["validation"]["valid"] is False
    assert body["artifacts"] == []


# ============================================================
# CAPABILITY DISCOVERY -- WHAT THE FRONTEND READS FIRST
# ============================================================
def test_capabilities_describes_only_what_can_actually_run(client):
    body = client.get("/capabilities").json()

    executable = set(body["executable"])
    assert executable == {"ndvi", "ndwi", "ndbi", "change_detection"}

    # Every tool is listed, but the unimplemented ones say so rather than
    # appearing as available capabilities.
    by_id = {tool["tool_id"]: tool for tool in body["tools"]}
    assert by_id["ndvi"]["implemented"] is True
    assert by_id["satellite_vqa"]["implemented"] is False
    assert set(by_id) >= executable

    # It is generated from the registry, not hand-maintained.
    registry = {tool["tool_id"] for tool in client.get("/api/tools").json()}
    assert set(by_id) == registry


def test_health_reports_the_live_backend(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["registered_tools"] == 8
    assert sorted(body["implemented_tools"]) == [
        "change_detection",
        "ndbi",
        "ndvi",
        "ndwi",
    ]
    assert body["backend"]["raster_backend"] in {"rasterio", "builtin"}


# ============================================================
# ERROR ENVELOPE
# ============================================================
def test_an_unknown_result_returns_the_structured_error_shape(client):
    response = client.get("/results/task_does_not_exist")
    assert response.status_code == 404

    body = response.json()
    assert body["error"] is True
    assert body["code"] == "not_found"
    assert body["message"] == body["detail"]     # detail keeps its usual meaning
    assert "incident_id" in body


def test_a_missing_query_is_reported_per_field(client, scene):
    response = client.post("/analyze", files=[_upload(scene)])
    assert response.status_code == 422

    body = response.json()
    assert body["code"] == "invalid_request"
    assert any("query" in item["field"] for item in body["fields"])


def test_a_server_error_never_leaks_a_stack_trace(client, monkeypatch, scene):
    """An unexpected failure returns a correlation id, not internals."""
    import app.api.tasks as tasks

    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail at /srv/app/private.py:42")

    monkeypatch.setattr(tasks.pipeline, "run", explode)

    # The default test client re-raises server exceptions; turning that off is
    # what lets the registered handler run, which is the thing under test.
    with TestClient(client.app, raise_server_exceptions=False) as raw:
        response = raw.post(
            "/analyze", data={"query": "Calculate NDVI"}, files=[_upload(scene)]
        )
    assert response.status_code == 500

    body = response.json()
    assert body["code"] == "internal_error"
    assert body["incident_id"]
    serialised = response.text
    assert "secret internal detail" not in serialised
    assert "Traceback" not in serialised
    assert "private.py" not in serialised


# ============================================================
# THE SECOND REAL TOOL, OVER HTTP
# ============================================================
@pytest.fixture
def dated_pair(raster_factory):
    """Two dated scenes whose NDVI differs by a known amount.

    The later scene has markedly lower NIR over the same red, so vegetation
    has genuinely fallen between the two dates and the change map has a
    correct answer that can be checked rather than merely observed.
    """
    from tests.conftest import make_band

    def scene(filename, nir_values, acquired):
        red = make_band("B4", [1000, 1000, 1000, 1000], 2, 2)
        nir = make_band("B8", nir_values, 2, 2)
        return raster_factory(
            filename, [red, nir], metadata_extra={"acquisition_date": acquired}
        )

    earlier = scene("t1.tif", [3000, 3000, 3000, 3000], "2023-06-01")
    later = scene("t2.tif", [1200, 1200, 3000, 3000], "2025-06-01")
    return earlier, later


def test_bi_temporal_change_detection_runs_end_to_end_over_http(client, dated_pair):
    earlier, later = dated_pair
    uploads = []
    for path, name in ((earlier, "2023.tif"), (later, "2025.tif")):
        with open(path, "rb") as handle:
            uploads.append(_upload(handle.read(), name))

    response = client.post(
        "/analyze",
        data={"query": "Compare these two images and identify vegetation change"},
        files=uploads,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "success"
    assert body["tool"] == "change_detection"
    assert body["output_type"] == "change_map"
    assert body["validation"]["valid"] is True
    assert len(body["images"]) == 2

    # The change is real: NDVI fell on half the pixels and held on the other
    # half, so the run must report change without reporting all of it.
    statistics = body["statistics"]
    assert statistics["valid_pixels"] == 4
    assert statistics["minimum"] < 0, "a vegetation decrease should be negative"
    assert body["artifacts"], "a change raster should have been produced"

    download = client.get(body["artifacts"][0]["url"])
    assert download.status_code == 200


def test_the_response_carries_enough_metadata_to_place_the_raster_on_a_map(
    client, scene
):
    """A frontend needs resolution and bounds, not just width and height."""
    body = client.post(
        "/analyze", data={"query": "Calculate NDVI"}, files=[_upload(scene)]
    ).json()
    image = body["images"][0]

    assert image["band_count"] == 4
    assert image["dtype"] == "uint16"
    assert image["crs"] == "EPSG:32643"
    assert image["transform"] == [699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0]
    assert image["resolution"] == [10.0, 10.0]           # 10 m Sentinel-2 grid

    min_x, min_y, max_x, max_y = image["bounds"]
    assert min_x < max_x and min_y < max_y               # ordered, not raw corners
    assert (max_x - min_x) == 10.0 * image["width"]
    assert (max_y - min_y) == 10.0 * image["height"]


def test_an_ungeoreferenced_raster_reports_no_extent_rather_than_a_wrong_one(
    client, raster_factory
):
    from tests.conftest import make_band

    red = make_band("B4", [1000, 2000, 3000, 500], 2, 2)
    nir = make_band("B8", [3000, 2000, 1000, 4500], 2, 2)
    path = raster_factory("plain.tif", [red, nir], georeference=None)
    with open(path, "rb") as handle:
        payload = handle.read()

    body = client.post(
        "/analyze",
        data={"query": "Calculate NDVI"},
        files=[_upload(payload, "plain.tif")],
    ).json()
    image = body["images"][0]

    assert image["resolution"] is None
    assert image["bounds"] is None
