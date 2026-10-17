"""Storage that does not grow without bound, and requests that are bounded too."""

from __future__ import annotations

import io
import os
import time

import pytest
from fastapi.testclient import TestClient

from app.api.store import TaskRecord, TaskStore, task_store
from app.api.tasks import MAX_LOCATION_CHARS, MAX_QUERY_CHARS
from app.config.settings import reset_settings
from app.controller.pipeline import SatQueryPipeline
from app.controller.task_understanding.task_understanding import TaskUnderstanding
from app.main import create_app
from app.storage.artifacts import LocalArtifactStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "storage"))
    reset_settings()
    task_store.clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    task_store.clear()
    reset_settings()


def _age(path: str, seconds: float) -> None:
    then = time.time() - seconds
    for parent, _, names in os.walk(path):
        for name in names:
            os.utime(os.path.join(parent, name), (then, then))
        os.utime(parent, (then, then))


# ============================================================
# RETENTION
# ============================================================
def test_old_task_directories_are_purged_and_recent_ones_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path))
    reset_settings()
    store = LocalArtifactStore()
    old = store.write_upload("task_old", b"x", ".tif")
    store.output_directory("task_old")
    new = store.write_upload("task_new", b"x", ".tif")
    _age(os.path.join(tmp_path, "uploads", "task_old"), 3 * 86400)
    _age(os.path.join(tmp_path, "outputs", "task_old"), 3 * 86400)
    # Something an operator keeps under the root is never touched.
    keep = os.path.join(tmp_path, "uploads", "not a task")
    os.makedirs(keep)
    _age(keep, 3 * 86400)

    assert store.purge_older_than(86400) == 1
    assert not os.path.exists(old)
    assert not os.path.isdir(os.path.join(tmp_path, "outputs", "task_old"))
    assert os.path.exists(new)
    assert os.path.isdir(keep)
    reset_settings()


def test_startup_purges_files_left_by_an_earlier_process(tmp_path, monkeypatch):
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path))
    reset_settings()
    path = LocalArtifactStore().write_upload("task_stale", b"x", ".tif")
    _age(os.path.join(tmp_path, "uploads", "task_stale"), 2 * 86400)
    create_app()
    assert not os.path.exists(path)

    monkeypatch.setenv("SATQUERY_RETENTION_HOURS", "0")
    reset_settings()
    path = LocalArtifactStore().write_upload("task_kept", b"x", ".tif")
    _age(os.path.join(tmp_path, "uploads", "task_kept"), 30 * 86400)
    create_app()
    assert os.path.exists(path)
    reset_settings()


def test_a_task_pushed_out_of_the_store_has_its_files_deleted():
    evicted: list[str] = []
    store = TaskStore(capacity=2, on_evict=evicted.append)
    for index in range(3):
        run = SatQueryPipeline().run("Calculate NDVI", [], task_id=f"task_{index}")
        store.save(TaskRecord(run=run))
    assert evicted == ["task_0"]
    assert store.get("task_0") is None


# ============================================================
# REQUEST LIMITS
# ============================================================
def test_an_overlong_question_is_refused(client):
    response = client.post("/api/tasks", data={"query": "a" * (MAX_QUERY_CHARS + 1)})
    assert response.status_code == 400
    assert "characters" in response.json()["detail"]


def test_an_overlong_location_is_refused(client):
    response = client.post(
        "/api/tasks",
        data={"query": "NDVI", "location": "x" * (MAX_LOCATION_CHARS + 1)},
    )
    assert response.status_code == 400
    assert "location" in response.json()["detail"]


def test_a_check_without_imagery_explains_itself(client):
    response = client.post("/api/tasks/validate", data={"query": "NDVI of Pune"})
    assert response.status_code == 400
    assert "Checking needs attached imagery" in response.json()["detail"]


def test_a_check_with_imagery_still_runs(client, sentinel2_scene):
    with open(sentinel2_scene, "rb") as handle:
        content = handle.read()
    response = client.post(
        "/api/tasks/validate",
        data={"query": "Calculate NDVI"},
        files=[("files", ("scene.tif", io.BytesIO(content), "image/tiff"))],
    )
    assert response.status_code == 200
    assert response.json()["would_execute"] is True


# ============================================================
# QUESTION READING
# ============================================================
@pytest.mark.parametrize(
    "query, task",
    [
        ("Is there a river near Varanasi?", "image_analysis"),
        ("Does the scene show a dam?", "image_analysis"),
        # Specific phrases still win over the yes/no fallback.
        ("Is the vegetation healthy in Pune?", "ndvi"),
        ("Is there vegetation loss between 2019 and 2024?", "change_detection"),
        ("Tell me something interesting about Pune", None),
    ],
)
def test_yes_no_questions_go_to_the_vision_model(query, task):
    assert TaskUnderstanding().understand(query).task_type == task
