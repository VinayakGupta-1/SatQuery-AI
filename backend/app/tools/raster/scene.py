"""Assembling one logical scene from several per-band raster files.

Real satellite products do not arrive as a single stacked raster. A Sentinel-2
L2A product is a directory of JPEG-2000 files, one per band, at three different
resolutions. Landsat Collection-2 is a directory of per-band GeoTIFFs. Until
SatQuery could read those, a user had to pre-stack their imagery by hand before
the system would look at it.

A scene is described by a small JSON manifest naming its band files. Opening
the manifest opens every band, resamples them onto one grid, and returns a
single :class:`RasterDataset` -- so everything above this layer continues to
see one image with named bands, exactly as before.

The finest-resolution band defines the target grid. Coarser bands are sampled
onto it; the reverse would throw away the detail the sensor captured.
Reprojection is *not* performed: bands in different coordinate systems are
refused, because silently reprojecting a user's product is the kind of hidden
transformation this system exists to avoid.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from app.tools.raster.model import BandArray, RasterDataset, RasterError
from app.tools.raster.resample import NEAREST, grids_match, resample_band

SCENE_MANIFEST_SUFFIX = ".satquery-scene.json"
MANIFEST_TYPE = "satquery_scene"

#: Raster extensions worth considering when scanning a product directory.
SCANNABLE_EXTENSIONS = (".tif", ".tiff", ".jp2")

#: Matches the band token in a product filename, e.g. the "B04" in
#: "T43RGM_20250311T053649_B04_10m.jp2" or "LC09_..._SR_B5.TIF".
BAND_TOKEN = re.compile(r"^(?:sr_|st_|toa_)?(b\d{1,2}[a-z]?)$", re.IGNORECASE)

#: Quality and classification layers, which do not follow the "B04" pattern but
#: are essential: they carry the cloud mask that makes an index trustworthy.
#: Sentinel-2 L2A ships SCL; Landsat Collection-2 ships QA_PIXEL.
QUALITY_BAND_SUFFIXES = (
    "qa_pixel",
    "qa_radsat",
    "pixel_qa",
    "cloud_mask",
    "cloudmask",
    "fmask",
    "scl",
)

#: Trailing resolution markers Sentinel-2 appends, e.g. "_10m".
RESOLUTION_SUFFIX = re.compile(r"_\d{2}m$", re.IGNORECASE)

#: Product naming conventions that identify the sensor. Knowing the sensor is
#: not cosmetic: band 11 is SWIR on Sentinel-2 and thermal on Landsat-8, so
#: without it an index would either fail or be computed from the wrong
#: wavelengths. Mission identifiers are the one reliable place to find it when
#: a product directory carries no other metadata.
SENSOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^S2[A-D][_\W]", re.IGNORECASE), "sentinel2"),
    (re.compile(r"^S1[A-D][_\W]", re.IGNORECASE), "sentinel1"),
    (re.compile(r"^L[COTEM]0?[89][_\W]", re.IGNORECASE), "landsat8"),
    (re.compile(r"^L[COTEM]0?7[_\W]", re.IGNORECASE), "landsat7"),
)


def sensor_from_product_name(name: str) -> str | None:
    """Infer the sensor from a product directory or file name."""
    base = os.path.basename(name.rstrip(os.sep).rstrip("/"))
    for pattern, sensor in SENSOR_PATTERNS:
        if pattern.match(base):
            return sensor
    return None


def is_scene_manifest(path: str) -> bool:
    return path.lower().endswith(SCENE_MANIFEST_SUFFIX)


# ============================================================
# MANIFESTS
# ============================================================
def write_scene_manifest(
    path: str,
    bands: list[dict[str, str]],
    metadata: dict[str, Any] | None = None,
    resampling: str = NEAREST,
) -> str:
    """Write a scene manifest.

    ``bands`` is a list of ``{"name": ..., "path": ...}`` entries. Paths may be
    absolute or relative to the manifest's own directory.
    """
    if not bands:
        raise RasterError("A scene manifest must list at least one band.")
    for entry in bands:
        if not entry.get("name") or not entry.get("path"):
            raise RasterError("Each scene band needs both a 'name' and a 'path'.")

    document = {
        "type": MANIFEST_TYPE,
        "resampling": resampling,
        "bands": bands,
        **(metadata or {}),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
    return path


def read_scene_manifest(path: str) -> dict[str, Any]:
    """Load and check a scene manifest."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as error:
        raise RasterError(f"Could not read scene manifest {path}: {error}") from error

    if not isinstance(document, dict):
        raise RasterError(f"Scene manifest {path} must contain a JSON object.")
    if document.get("type") != MANIFEST_TYPE:
        raise RasterError(
            f"{path} is not a SatQuery scene manifest (expected type "
            f"'{MANIFEST_TYPE}')."
        )
    if not isinstance(document.get("bands"), list) or not document["bands"]:
        raise RasterError(f"Scene manifest {path} lists no bands.")
    return document


# ============================================================
# OPENING A SCENE
# ============================================================
def open_scene(manifest_path: str, opener) -> RasterDataset:
    """Open every band a manifest names and stack them onto one grid.

    ``opener`` reads a single raster file; it is injected so this module does
    not import the backend-selecting I/O layer that in turn dispatches here.
    """
    document = read_scene_manifest(manifest_path)
    directory = os.path.dirname(os.path.abspath(manifest_path))

    sources: list[tuple[str, RasterDataset]] = []
    for entry in document["bands"]:
        name = str(entry.get("name") or "").strip()
        raw_path = str(entry.get("path") or "").strip()
        if not name or not raw_path:
            raise RasterError("Each scene band needs both a 'name' and a 'path'.")

        path = raw_path if os.path.isabs(raw_path) else os.path.join(directory, raw_path)
        if not os.path.exists(path):
            raise RasterError(
                f"Scene band '{name}' refers to {raw_path}, which does not exist "
                f"relative to {directory}."
            )
        sources.append((name, opener(path)))

    metadata = {
        key: value
        for key, value in document.items()
        if key not in ("type", "bands", "resampling")
    }
    return stack_scene(
        sources,
        resampling=str(document.get("resampling") or NEAREST),
        metadata=metadata,
        path=manifest_path,
    )


def stack_scene(
    sources: list[tuple[str, RasterDataset]],
    resampling: str = NEAREST,
    metadata: dict[str, Any] | None = None,
    path: str | None = None,
) -> RasterDataset:
    """Combine per-band datasets into one, resampling to the finest grid."""
    if not sources:
        raise RasterError("A scene needs at least one band.")

    _require_common_crs(sources)
    reference_name, reference = _finest(sources)

    bands: list[BandArray] = []
    resampled: list[str] = []

    for name, dataset in sources:
        if dataset.band_count != 1:
            raise RasterError(
                f"Scene band '{name}' comes from a file with {dataset.band_count} "
                "bands. Each entry in a scene manifest must name a single-band file."
            )

        band = dataset.band_at(1)
        if dataset is reference or grids_match(
            dataset.georeference,
            (dataset.height, dataset.width),
            reference.georeference,
            (reference.height, reference.width),
        ):
            bands.append(
                BandArray(
                    name=name,
                    width=band.width,
                    height=band.height,
                    values=band.values,
                    dtype=band.dtype,
                    nodata=band.nodata,
                )
            )
            continue

        bands.append(
            resample_band(
                BandArray(
                    name=name,
                    width=band.width,
                    height=band.height,
                    values=band.values,
                    dtype=band.dtype,
                    nodata=band.nodata,
                ),
                source=dataset.georeference,
                target=reference.georeference,
                target_width=reference.width,
                target_height=reference.height,
                method=resampling,
            )
        )
        resampled.append(name)

    combined = dict(metadata or {})
    combined.setdefault("band_names", [band.name for band in bands])
    combined["scene_reference_band"] = reference_name
    if resampled:
        combined["resampled_bands"] = resampled
        combined["resampling_method"] = resampling

    return RasterDataset(
        width=reference.width,
        height=reference.height,
        bands=bands,
        georeference=reference.georeference,
        dtype=bands[0].dtype,
        nodata=bands[0].nodata,
        path=path,
        metadata=combined,
    )


def _require_common_crs(sources: list[tuple[str, RasterDataset]]) -> None:
    systems = {
        dataset.georeference.crs
        for _, dataset in sources
        if dataset.georeference.crs
    }
    if len(systems) > 1:
        raise RasterError(
            f"The scene's bands use different coordinate reference systems "
            f"({sorted(systems)}). Reproject them to a common CRS before "
            "combining them; SatQuery does not reproject silently."
        )


def _finest(sources: list[tuple[str, RasterDataset]]) -> tuple[str, RasterDataset]:
    """Return the band whose pixels cover the least ground.

    Resampling coarse bands up to the finest grid preserves the detail the
    sensor recorded; doing the reverse would discard it.
    """
    def ranking(item: tuple[str, RasterDataset]):
        name, dataset = item
        area = dataset.georeference.pixel_area()
        # Ungeoreferenced bands cannot define a grid, so rank them last.
        return (area if area is not None else float("inf"), -dataset.width, name)

    return min(sources, key=ranking)


# ============================================================
# PRODUCT DIRECTORIES
# ============================================================
def band_name_from_filename(filename: str) -> str | None:
    """Extract the band identifier from a product filename, if it has one.

    Recognises both spectral bands ("B04") and quality layers ("SCL",
    "QA_PIXEL"). Returns ``None`` for anything else, so previews and metadata
    files in a product directory are skipped rather than loaded as bands.
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    trimmed = RESOLUTION_SUFFIX.sub("", stem).lower()

    for suffix in QUALITY_BAND_SUFFIXES:
        if trimmed == suffix or trimmed.endswith("_" + suffix):
            return suffix.upper()

    for token in reversed(stem.split("_")):
        match = BAND_TOKEN.match(token)
        if match:
            return match.group(1).upper()
    return None


def discover_scene_bands(directory: str) -> list[dict[str, str]]:
    """Find per-band raster files beneath ``directory``.

    Product layouts nest their imagery (Sentinel-2 SAFE puts it several levels
    down under ``GRANULE``), so the search is recursive. When the same band
    appears at several resolutions, the finest file wins -- these are the same
    measurement, and the coarser copies would be redundant bands.
    """
    found: dict[str, tuple[int, str]] = {}

    for root, _, filenames in os.walk(directory):
        for filename in sorted(filenames):
            if not filename.lower().endswith(SCANNABLE_EXTENSIONS):
                continue
            name = band_name_from_filename(filename)
            if not name:
                continue

            path = os.path.join(root, filename)
            resolution = _resolution_hint(filename, root)
            existing = found.get(name)
            if existing is None or resolution < existing[0]:
                found[name] = (resolution, path)

    return [
        {"name": name, "path": path}
        for name, (_, path) in sorted(found.items())
    ]


def _resolution_hint(filename: str, root: str) -> int:
    """Read a resolution in metres from a filename or its directory, if stated.

    Sentinel-2 marks these as ``_10m`` in the filename and ``R10m`` in the
    directory name. Absent any marker the file ranks last, so an explicitly
    finer file is always preferred.
    """
    for text in (filename, os.path.basename(root)):
        match = re.search(r"[_R](\d{2})m\b", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 9999


def open_scene_directory(directory: str, opener) -> RasterDataset:
    """Open a product directory as one scene."""
    for entry in sorted(os.listdir(directory)):
        if is_scene_manifest(entry):
            return open_scene(os.path.join(directory, entry), opener)

    bands = discover_scene_bands(directory)
    if not bands:
        raise RasterError(
            f"No per-band raster files were found under {directory}. Supply a "
            f"'{SCENE_MANIFEST_SUFFIX}' manifest naming the bands explicitly."
        )

    sources = [(entry["name"], opener(entry["path"])) for entry in bands]

    # A band file may already declare its sensor; otherwise fall back to the
    # mission identifier in the product name.
    metadata: dict[str, Any] = {}
    declared = next(
        (
            dataset.metadata["sensor"]
            for _, dataset in sources
            if dataset.metadata.get("sensor")
        ),
        None,
    )
    sensor = declared or sensor_from_product_name(directory)
    if sensor:
        metadata["sensor"] = sensor

    return stack_scene(sources, metadata=metadata, path=directory)
