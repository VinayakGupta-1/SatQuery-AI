"""Turning HTTP uploads into validated pipeline inputs.

Two responsibilities live here, both security-relevant:

*Storage.* A client-supplied filename is never used as a path. Uploads are
stored under a server-generated name inside a per-task directory, which removes
path traversal and collisions in one step.

*Description.* Each stored raster is opened and described, so the metadata the
validator checks comes from the file itself rather than from the client. A
caller cannot claim their SAR scene is optical to slip past validation.
"""

from __future__ import annotations

import os
import re
import uuid

from app.api.schemas import ImageSummary
from app.config.settings import Settings
from app.schemas.inputs import ImageInput, ImageMetadata
from app.tools.raster.inspection import describe_raster
from app.tools.raster.model import RasterError
from app.tools.raster.scene import (
    SCENE_MANIFEST_SUFFIX,
    band_name_from_filename,
    write_scene_manifest,
)

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class IngestionError(Exception):
    """An upload could not be accepted."""


def safe_filename(filename: str | None) -> str:
    """Reduce a client filename to something safe to display and store."""
    base = os.path.basename(filename or "").strip()
    base = SAFE_NAME.sub("_", base).lstrip(".")
    return base[:120] or "upload"


def check_extension(filename: str, settings: Settings) -> str:
    """Return the extension of ``filename`` if it is an accepted raster type."""
    extension = os.path.splitext(filename)[1].lower()
    if extension not in settings.allowed_extensions:
        raise IngestionError(
            f"'{filename}' has an unsupported extension. Accepted types: "
            f"{', '.join(settings.allowed_extensions)}."
        )
    return extension


def store_upload(
    content: bytes,
    filename: str | None,
    task_id: str,
    settings: Settings,
) -> tuple[str, str]:
    """Write one upload to disk under a server-generated name.

    Returns ``(stored_path, display_name)``.
    """
    display = safe_filename(filename)
    extension = check_extension(display, settings)

    if not content:
        raise IngestionError(f"'{display}' is empty.")
    if len(content) > settings.max_upload_bytes:
        raise IngestionError(
            f"'{display}' is {len(content):,} bytes, over the "
            f"{settings.max_upload_bytes:,} byte limit."
        )

    directory = settings.task_upload_directory(task_id)
    os.makedirs(directory, exist_ok=True)

    # The stored name is ours, never the client's.
    stored = os.path.join(directory, f"{uuid.uuid4().hex}{extension}")
    with open(stored, "wb") as handle:
        handle.write(content)
    return stored, display


def assemble_scene(
    stored: list[tuple[str, str]],
    task_id: str,
    settings: Settings,
    sensor: str | None = None,
) -> str:
    """Write a manifest declaring several uploaded files to be one scene.

    Real products ship one file per band, so a user uploading B04 and B08 is
    describing a single image, not two. The manifest records that, and opening
    it resamples the bands onto a common grid.
    """
    bands = []
    for index, (path, display) in enumerate(stored, start=1):
        name = band_name_from_filename(display) or os.path.splitext(display)[0]
        if any(entry["name"] == name for entry in bands):
            name = f"{name}_{index}"
        bands.append({"name": name, "path": path})

    metadata: dict[str, str] = {}
    if sensor and sensor.strip():
        metadata["sensor"] = sensor.strip()

    manifest = os.path.join(
        settings.task_upload_directory(task_id), f"scene{SCENE_MANIFEST_SUFFIX}"
    )
    try:
        write_scene_manifest(manifest, bands, metadata=metadata)
    except RasterError as error:
        raise IngestionError(str(error)) from error
    return manifest


def describe_upload(path: str, image_id: str, display_name: str) -> tuple[ImageInput, ImageSummary]:
    """Open a stored raster and describe it for the pipeline and the client."""
    try:
        metadata: ImageMetadata = describe_raster(path)
    except RasterError as error:
        raise IngestionError(f"'{display_name}' could not be read as a raster: {error}") from error

    image = ImageInput(id=image_id, path=path, metadata=metadata)
    summary = ImageSummary(
        id=image_id,
        filename=display_name,
        width=metadata.width,
        height=metadata.height,
        crs=metadata.crs,
        modality=metadata.modality,
        sensor=metadata.sensor,
        bands=metadata.bands,
        acquisition_date=(
            metadata.acquisition_date.isoformat() if metadata.acquisition_date else None
        ),
    )
    return image, summary
