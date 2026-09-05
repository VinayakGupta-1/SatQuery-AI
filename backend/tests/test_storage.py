"""Tests for the artifact storage layer.

Storage is where a path-traversal bug would live, so most of these are about
refusing to leave the storage root rather than about reading and writing.
"""

from __future__ import annotations

import os

import pytest

from app.config.settings import Settings
from app.storage.artifacts import (
    LocalArtifactStore,
    StorageError,
    get_artifact_store,
    reset_artifact_store,
)


@pytest.fixture
def store(tmp_path):
    settings = Settings(storage_root=str(tmp_path / "storage"))
    return LocalArtifactStore(settings)


# ============================================================
# CREATION AND RETRIEVAL
# ============================================================
def test_an_upload_is_written_and_can_be_read_back(store):
    path = store.write_upload("task_abc", b"raster-bytes", ".tif")

    assert store.exists(path)
    assert store.size(path) == len(b"raster-bytes")
    with open(path, "rb") as handle:
        assert handle.read() == b"raster-bytes"


def test_uploads_and_outputs_are_separated_per_task(store):
    assert store.upload_directory("task_a") != store.upload_directory("task_b")
    assert store.upload_directory("task_a") != store.output_directory("task_a")
    assert os.path.isdir(store.output_directory("task_a"))


def test_the_stored_name_is_generated_not_taken_from_the_client(store):
    """Two uploads never collide, and the client never chooses the name."""
    first = store.write_upload("task_abc", b"a", ".tif")
    second = store.write_upload("task_abc", b"b", ".tif")

    assert first != second
    assert os.path.basename(first) != os.path.basename(second)


def test_deleting_a_task_removes_its_files(store):
    path = store.write_upload("task_abc", b"data", ".tif")
    store.output_directory("task_abc")

    store.delete_task("task_abc")

    assert not os.path.exists(path)


# ============================================================
# CONTAINMENT
# ============================================================
@pytest.mark.parametrize(
    "hostile",
    [
        "../../../../etc/passwd",
        "..",
        "task/../../..",
        "a/../../b",
    ],
)
def test_a_traversing_task_id_is_refused(store, hostile):
    with pytest.raises(StorageError):
        store.upload_directory(hostile)


@pytest.mark.parametrize("hostile", ["", "  ", "a" * 200, "task id", "task;rm"])
def test_an_unusable_task_id_is_refused(store, hostile):
    with pytest.raises(StorageError):
        store.upload_directory(hostile)


def test_resolving_a_path_outside_the_root_is_refused(store, tmp_path):
    outside = tmp_path / "outside.tif"
    outside.write_bytes(b"x")

    with pytest.raises(StorageError):
        store.resolve(str(outside))
    assert store.exists(str(outside)) is False
    assert store.contains(str(outside)) is False


def test_a_path_inside_the_root_is_accepted(store):
    path = store.write_upload("task_abc", b"data", ".tif")
    assert store.contains(path)
    assert store.resolve(path) == os.path.realpath(path)


@pytest.mark.parametrize("extension", ["", ".", ".tif/../..", ".exe;", "." + "x" * 40])
def test_a_hostile_extension_is_refused(store, extension):
    with pytest.raises(StorageError):
        store.write_upload("task_abc", b"data", extension)


# ============================================================
# CONFIGURATION
# ============================================================
def test_the_shared_store_follows_the_current_configuration(monkeypatch, tmp_path):
    """A cached store must not pin the storage root it was first built with."""
    reset_artifact_store()
    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "one"))
    from app.config.settings import reset_settings

    reset_settings()
    assert str(tmp_path / "one") in get_artifact_store().upload_directory("t1")

    monkeypatch.setenv("SATQUERY_STORAGE_ROOT", str(tmp_path / "two"))
    reset_settings()
    assert str(tmp_path / "two") in get_artifact_store().upload_directory("t1")

    reset_settings()
    reset_artifact_store()
