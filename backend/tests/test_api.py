"""Tests for the HTTP API, driven through a real ASGI client.

These exercise the whole stack: multipart upload, ingestion, metadata read
from the file itself, the ten pipeline stages, and the response shaping --
including artifact download, which returns a GeoTIFF that is then reopened and
checked pixel by pixel.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.store import task_store
from app.config.settings import get_settings, reset_settings
from app.main import create_app
from app.tools.raster.io import open_raster
from tests.conftest import SENTINEL2_EXPECTED_NDVI


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client whose storage lives in a per-test directory."""
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    reset_settings()
    task_store.clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    task_store.clear()
    reset_settings()


@pytest.fixture
def scene_bytes(sentinel2_scene):
    with open(sentinel2_scene, "rb") as handle:
        return handle.read()


@pytest.fixture
def scene_sidecar(sentinel2_scene):
    with open(sentinel2_scene + ".satquery.json", "rb") as handle:
        return handle.read()


def upload(scene_bytes, name="scene.tif"):
    return ("files", (name, io.BytesIO(scene_bytes), "image/tiff"))


# ============================================================
# SYSTEM AND REGISTRY
# ============================================================
def test_health_reports_real_capabilities(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["registered_tools"] == 8
    assert set(body["implemented_tools"]) == {
        "ndvi", "ndwi", "ndbi", "change_detection",
    }
    assert body["backend"]["raster_backend"] in ("rasterio", "builtin")


def test_registry_is_published(client):
    tools = client.get("/api/tools").json()

    assert len(tools) == 8
    ndvi = next(tool for tool in tools if tool["tool_id"] == "ndvi")
    assert ndvi["implemented"] is True
    assert ndvi["required_bands"] == ["red", "nir"]
    assert "red_band" in ndvi["parameters"]

    # A registered but unbuilt capability is labelled honestly.
    vqa = next(tool for tool in tools if tool["tool_id"] == "satellite_vqa")
    assert vqa["implemented"] is False


def test_registry_can_be_filtered_to_implemented_tools(client):
    tools = client.get("/api/tools", params={"implemented_only": True}).json()

    assert {tool["tool_id"] for tool in tools} == {
        "ndvi", "ndwi", "ndbi", "change_detection",
    }


def test_unknown_tool_is_404(client):
    assert client.get("/api/tools/nope").status_code == 404


# ============================================================
# RUNNING A TASK
# ============================================================
def test_ndvi_task_end_to_end_over_http(client, scene_bytes):
    response = client.post(
        "/api/tasks",
        data={"query": "Calculate vegetation health from this satellite image"},
        files=[upload(scene_bytes)],
    )

    assert response.status_code == 200
    body = response.json()

    assert body["outcome"] == "completed"
    assert "Mean NDVI is 0.200" in body["answer"]
    assert body["statistics"]["mean"] == pytest.approx(0.2)
    assert body["explanation"]["selected_tool"] == "ndvi"
    assert body["explanation"]["understood_task"] == "ndvi"
    assert body["validation"]["valid"] is True


def test_metadata_is_read_from_the_uploaded_file(client, scene_bytes):
    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[upload(scene_bytes)],
    ).json()

    image = body["images"][0]
    assert image["width"] == 2
    assert image["height"] == 2
    assert image["crs"] == "EPSG:32643"
    # Physical band names were mapped to the logical names the controller uses.
    assert image["bands"] == ["blue", "green", "red", "nir"]
    assert image["modality"] == "optical"


def test_explanation_exposes_the_decision_trail(client, scene_bytes):
    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[upload(scene_bytes)],
    ).json()
    explanation = body["explanation"]

    assert explanation["task_category"] == "index_analysis"
    assert explanation["required_bands"] == ["red", "nir"]
    assert explanation["resolved_parameters"]["red_band"] == "red"
    assert explanation["stage_status"]["execution"] == "completed"
    assert len(explanation["plan_steps"]) > 0
    assert explanation["selection_reason"]


def test_explicit_parameters_are_accepted(client, scene_bytes):
    body = client.post(
        "/api/tasks",
        data={
            "query": "Calculate NDVI",
            "parameters": '{"red_band": "B4", "nir_band": "B8"}',
        },
        files=[upload(scene_bytes)],
    ).json()

    assert body["outcome"] == "completed"
    assert body["data"]["formula"] == "(B8 - B4) / (B8 + B4)"


def test_malformed_parameters_are_rejected(client, scene_bytes):
    response = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI", "parameters": "not json"},
        files=[upload(scene_bytes)],
    )

    assert response.status_code == 400
    assert "not valid JSON" in response.json()["detail"]


# ============================================================
# ARTIFACTS
# ============================================================
def test_artifact_is_downloadable_and_correct(client, scene_bytes, tmp_path):
    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[upload(scene_bytes)],
    ).json()

    assert len(body["artifacts"]) == 1
    artifact = body["artifacts"][0]
    assert artifact["kind"] == "raster"
    assert artifact["url"].startswith(f"/api/tasks/{body['task_id']}/artifacts/")

    download = client.get(artifact["url"])
    assert download.status_code == 200

    # The bytes really are the NDVI raster.
    saved = tmp_path / "downloaded.tif"
    saved.write_bytes(download.content)
    assert open_raster(str(saved)).band_at(1).to_list() == pytest.approx(
        SENTINEL2_EXPECTED_NDVI, abs=1e-6
    )


def test_artifact_response_never_exposes_a_server_path(client, scene_bytes):
    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[upload(scene_bytes)],
    ).json()

    serialised = str(body)
    assert "C:\\" not in serialised
    assert "/tmp/" not in serialised
    assert "storage" not in serialised


def test_unknown_artifact_is_404(client, scene_bytes):
    body = client.post(
        "/api/tasks", data={"query": "Calculate NDVI"}, files=[upload(scene_bytes)]
    ).json()

    response = client.get(f"/api/tasks/{body['task_id']}/artifacts/does_not_exist")
    assert response.status_code == 404


def test_artifact_path_traversal_is_refused(client, scene_bytes):
    body = client.post(
        "/api/tasks", data={"query": "Calculate NDVI"}, files=[upload(scene_bytes)]
    ).json()

    # Only ids recorded on the task are served, so traversal cannot resolve.
    response = client.get(
        f"/api/tasks/{body['task_id']}/artifacts/..%2F..%2F..%2Fetc%2Fpasswd"
    )
    assert response.status_code == 404


# ============================================================
# RETRIEVAL
# ============================================================
def test_a_task_can_be_fetched_again(client, scene_bytes):
    created = client.post(
        "/api/tasks", data={"query": "Calculate NDVI"}, files=[upload(scene_bytes)]
    ).json()

    fetched = client.get(f"/api/tasks/{created['task_id']}").json()

    assert fetched["task_id"] == created["task_id"]
    assert fetched["answer"] == created["answer"]
    assert fetched["statistics"]["mean"] == pytest.approx(0.2)


def test_tasks_are_listed_newest_first(client, scene_bytes):
    client.post("/api/tasks", data={"query": "Calculate NDVI"}, files=[upload(scene_bytes)])
    client.post("/api/tasks", data={"query": "Calculate NDWI"}, files=[upload(scene_bytes)])

    listed = client.get("/api/tasks").json()

    assert len(listed) == 2
    assert listed[0]["query"] == "Calculate NDWI"


def test_unknown_task_is_404(client):
    assert client.get("/api/tasks/task_missing").status_code == 404


# ============================================================
# REJECTION PATHS RETURN 200 WITH AN EXPLANATION
# ============================================================
def test_sar_upload_is_rejected_with_a_reason(client, raster_factory, tmp_path):
    from tests.conftest import make_band

    # A raster whose bands are radar polarisations, not optical bands.
    vv = make_band("VV", [10, 20, 30, 40], 2, 2)
    vh = make_band("VH", [5, 6, 7, 8], 2, 2)
    path = raster_factory("sar.tif", [vv, vh], sensor="sentinel1")
    with open(path, "rb") as handle:
        content = handle.read()

    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI for this image"},
        files=[("files", ("sar.tif", io.BytesIO(content), "image/tiff"))],
    ).json()

    assert body["outcome"] == "rejected"
    assert body["validation"]["valid"] is False
    assert body["images"][0]["modality"] == "sar"
    assert "MODALITY_MISMATCH" in {
        issue["code"] for issue in body["validation"]["errors"]
    }
    assert body["artifacts"] == []


def test_unimplemented_capability_is_reported_not_faked(client, scene_bytes):
    body = client.post(
        "/api/tasks",
        data={"query": "What is in this image?"},
        files=[upload(scene_bytes)],
    ).json()

    assert body["explanation"]["selected_tool"] == "satellite_vqa"
    assert body["outcome"] == "blocked"
    assert "no execution implementation" in body["answer"]
    assert body["artifacts"] == []


# ============================================================
# INPUT GUARDS
# ============================================================
def test_empty_query_is_rejected(client, scene_bytes):
    response = client.post(
        "/api/tasks", data={"query": "   "}, files=[upload(scene_bytes)]
    )
    assert response.status_code == 400


def test_missing_file_is_rejected(client):
    response = client.post("/api/tasks", data={"query": "Calculate NDVI"})
    assert response.status_code == 422  # FastAPI's own required-field check


def test_non_raster_extension_is_rejected(client):
    response = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[("files", ("payload.exe", io.BytesIO(b"MZ..."), "application/exe"))],
    )

    assert response.status_code == 400
    assert "unsupported extension" in response.json()["detail"]


def test_corrupt_raster_is_rejected_at_ingestion(client):
    response = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[("files", ("broken.tif", io.BytesIO(b"not a tiff at all"), "image/tiff"))],
    )

    assert response.status_code == 400
    assert "could not be read as a raster" in response.json()["detail"]


def test_empty_file_is_rejected(client):
    response = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[("files", ("empty.tif", io.BytesIO(b""), "image/tiff"))],
    )
    assert response.status_code == 400


def test_too_many_files_are_rejected(client, scene_bytes):
    settings = get_settings()
    files = [
        upload(scene_bytes, f"scene_{index}.tif")
        for index in range(settings.max_images_per_task + 1)
    ]

    response = client.post("/api/tasks", data={"query": "Calculate NDVI"}, files=files)

    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


def test_oversized_upload_is_rejected(client, scene_bytes, monkeypatch):
    monkeypatch.setenv("SATQUERY_MAX_UPLOAD_BYTES", "10")
    reset_settings()

    response = client.post(
        "/api/tasks", data={"query": "Calculate NDVI"}, files=[upload(scene_bytes)]
    )

    assert response.status_code == 400
    assert "over the" in response.json()["detail"]


# ============================================================
# DRY-RUN VALIDATION
# ============================================================
def test_validate_endpoint_checks_without_executing(client, scene_bytes):
    body = client.post(
        "/api/tasks/validate",
        data={"query": "Calculate NDVI"},
        files=[upload(scene_bytes)],
    ).json()

    assert body["would_execute"] is True
    assert body["validation"]["valid"] is True
    assert body["selected_tool"] == "ndvi"
    # Nothing was stored, because nothing ran.
    assert client.get("/api/tasks").json() == []


def test_validate_endpoint_reports_incompatible_input(client, raster_factory):
    from tests.conftest import make_band

    vv = make_band("VV", [10, 20, 30, 40], 2, 2)
    path = raster_factory("sar.tif", [vv], sensor="sentinel1")
    with open(path, "rb") as handle:
        content = handle.read()

    body = client.post(
        "/api/tasks/validate",
        data={"query": "Calculate NDVI"},
        files=[("files", ("sar.tif", io.BytesIO(content), "image/tiff"))],
    ).json()

    assert body["would_execute"] is False
    assert body["validation"]["valid"] is False


# ============================================================
# DOCUMENTATION
# ============================================================
def test_openapi_schema_is_generated(client):
    schema = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "SatQuery AI"
    for path in ("/api/health", "/api/tools", "/api/tasks"):
        assert path in schema["paths"]


# ============================================================
# MULTI-FILE SCENES OVER HTTP
# ============================================================
@pytest.fixture
def band_files(tmp_path):
    """Two single-band files named the way a real product names them."""
    from app.tools.raster.io import write_raster
    from app.tools.raster.model import GeoReference
    from tests.conftest import make_band

    grid = GeoReference(
        crs="EPSG:32643", transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0)
    )
    written = []
    for name, values in (
        ("T43RGM_20250311_B04_10m.tif", [1000, 2000, 3000, 500]),
        ("T43RGM_20250311_B08_10m.tif", [3000, 2000, 1000, 4500]),
    ):
        path = str(tmp_path / name)
        write_raster(
            path, [make_band(name[:-4], values, 2, 2)], grid, dtype="uint16"
        )
        with open(path, "rb") as handle:
            written.append((name, handle.read()))
    return written


def test_per_band_files_upload_as_one_scene(client, band_files):
    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI", "as_scene": "true", "sensor": "sentinel2"},
        files=[
            ("files", (name, io.BytesIO(content), "image/tiff"))
            for name, content in band_files
        ],
    ).json()

    # Two files, but one image: they are bands of the same scene.
    assert len(body["images"]) == 1
    assert body["images"][0]["bands"] == ["red", "nir"]
    assert body["outcome"] == "completed"
    assert body["statistics"]["mean"] == pytest.approx(0.2)


def test_the_same_files_without_as_scene_are_separate_images(client, band_files):
    body = client.post(
        "/api/tasks",
        data={"query": "Calculate NDVI"},
        files=[
            ("files", (name, io.BytesIO(content), "image/tiff"))
            for name, content in band_files
        ],
    ).json()

    # Two separate single-band images, so NDVI has neither pair and the
    # validator refuses rather than guessing.
    assert len(body["images"]) == 2
    assert body["outcome"] == "rejected"
