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

from app.api.schemas import ImageSummary
from app.config.settings import Settings
from app.storage.artifacts import StorageError, get_artifact_store
from app.schemas.inputs import ImageInput, ImageMetadata
from app.tools.raster.inspection import describe_dataset
from app.tools.raster.io import open_raster
from app.tools.raster.model import RasterDataset, RasterError
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

    # The storage layer owns the path entirely: the client's filename never
    # becomes part of it, and the result is guaranteed to sit inside the
    # configured storage root.
    try:
        stored = get_artifact_store().write_upload(task_id, content, extension)
    except StorageError as error:
        raise IngestionError(str(error)) from error
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
        get_artifact_store().upload_directory(task_id), f"scene{SCENE_MANIFEST_SUFFIX}"
    )
    try:
        write_scene_manifest(manifest, bands, metadata=metadata)
    except RasterError as error:
        raise IngestionError(str(error)) from error
    return manifest


def _spatial_extent(dataset: RasterDataset) -> tuple[list[float] | None, list[float] | None]:
    """Return ``(resolution, bounds)`` for a dataset, when it is georeferenced."""
    # A raster with no georeferencing still reports a transform under GDAL --
    # the identity matrix. Deriving a resolution from that would claim
    # one-unit pixels and an extent anchored at the origin, which is worse
    # than reporting nothing. Only a genuinely georeferenced raster gets an
    # extent.
    if not dataset.georeference.is_georeferenced:
        return None, None

    transform = dataset.georeference.transform
    if transform is None:
        return None, None

    origin_x, pixel_w, _, origin_y, _, pixel_h = transform
    resolution = [abs(pixel_w), abs(pixel_h)]

    # pixel_h is normally negative, so the far corner is computed rather than
    # assumed, and the pairs are then ordered into (min, max).
    far_x = origin_x + pixel_w * dataset.width
    far_y = origin_y + pixel_h * dataset.height
    bounds = [
        min(origin_x, far_x),
        min(origin_y, far_y),
        max(origin_x, far_x),
        max(origin_y, far_y),
    ]
    return resolution, bounds


def describe_upload(path: str, image_id: str, display_name: str) -> tuple[ImageInput, ImageSummary]:
    """Open a stored raster and describe it for the pipeline and the client.

    The file is opened once and both descriptions are derived from that one
    read: the minimal metadata the validator reasons about, and the fuller
    geospatial summary a frontend needs to place the raster on a map.
    """
    try:
        dataset = open_raster(path)
    except RasterError as error:
        raise IngestionError(f"'{display_name}' could not be read as a raster: {error}") from error

    metadata: ImageMetadata = describe_dataset(dataset)
    resolution, bounds = _spatial_extent(dataset)

    image = ImageInput(id=image_id, path=path, metadata=metadata)
    summary = ImageSummary(
        id=image_id,
        filename=display_name,
        width=metadata.width,
        height=metadata.height,
        band_count=dataset.band_count,
        dtype=dataset.dtype,
        nodata=dataset.nodata,
        crs=metadata.crs,
        transform=list(dataset.georeference.transform)
        if dataset.georeference.is_georeferenced
        else None,
        resolution=resolution,
        bounds=bounds,
        modality=metadata.modality,
        sensor=metadata.sensor,
        bands=metadata.bands,
        acquisition_date=(
            metadata.acquisition_date.isoformat() if metadata.acquisition_date else None
        ),
    )
    return image, summary
