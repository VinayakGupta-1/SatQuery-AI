"""Artifact storage.

Every path the system reads or writes is produced here, so no other module
contains a hardcoded directory and swapping local disk for object storage is a
matter of implementing one interface.
"""

from app.storage.artifacts import (
    ArtifactStore,
    LocalArtifactStore,
    StorageError,
    get_artifact_store,
    reset_artifact_store,
)

__all__ = [
    "ArtifactStore",
    "LocalArtifactStore",
    "StorageError",
    "get_artifact_store",
    "reset_artifact_store",
]
