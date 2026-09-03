"""Raster input/output with a pluggable backend.

Two backends are supported and selected automatically:

``rasterio``
    Used whenever it is importable. It brings GDAL, so it handles compressed
    and tiled GeoTIFFs, JPEG2000 Sentinel-2 products, overviews, and full CRS
    descriptions.

``builtin``
    The dependency-free reader in :mod:`app.tools.raster.tiff`. It handles
    uncompressed baseline GeoTIFF and keeps the tool layer fully functional on
    a machine with nothing but the standard library installed.

Callers use :func:`open_raster` and :func:`write_raster` and never import a
backend directly, so ``pip install rasterio`` upgrades the whole tool layer
without any code change.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.tools.raster import tiff
from app.tools.raster.backends import (
    BACKEND_ENV_VAR,
    active_backend,
    backend_report,
    has_numpy,
    has_rasterio,
)
from app.tools.raster.scene import (
    is_scene_manifest,
    open_scene,
    open_scene_directory,
)
from app.tools.raster.model import (
    DTYPE_TO_TYPECODE,
    BandArray,
    GeoReference,
    RasterDataset,
    RasterError,
    UnsupportedRasterError,
)

GEOTIFF_EXTENSIONS = {".tif", ".tiff", ".gtif", ".gtiff"}
SIDECAR_SUFFIX = ".satquery.json"


# ============================================================
# BACKEND DETECTION
# ============================================================
# Detection itself lives in app.tools.raster.backends so that low-level modules
# can consult it without importing this one. The names are re-exported here
# because this is where callers expect to find them.
__all__ = [
    "BACKEND_ENV_VAR",
    "active_backend",
    "backend_report",
    "has_numpy",
    "has_rasterio",
    "open_raster",
    "write_raster",
    "write_sidecar",
]


# ============================================================
# METADATA SIDECAR
# ============================================================
def _read_sidecar(path: str) -> dict[str, Any]:
    """Read optional ``<raster><SIDECAR_SUFFIX>`` metadata.

    Band names and the sensor are frequently absent from the GeoTIFF itself.
    A sidecar lets a dataset declare them without inventing values.
    """
    sidecar = path + SIDECAR_SUFFIX
    if not os.path.exists(sidecar):
        return {}
    try:
        with open(sidecar, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise RasterError(f"Could not read raster sidecar {sidecar}: {error}") from error
    if not isinstance(data, dict):
        raise RasterError(f"Raster sidecar {sidecar} must contain a JSON object.")
    return data


def write_sidecar(path: str, metadata: dict[str, Any]) -> str:
    """Write a metadata sidecar next to a raster."""
    sidecar = path + SIDECAR_SUFFIX
    with open(sidecar, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
    return sidecar


# ============================================================
# READING
# ============================================================
def open_raster(path: str, band_names: list[str] | None = None) -> RasterDataset:
    """Open a raster into an in-memory :class:`RasterDataset`.

    ``path`` may be a single raster file, a scene manifest naming several
    per-band files, or a product directory containing them. All three yield one
    dataset with named bands, so callers never have to know which they were
    given.
    """
    if not isinstance(path, str) or not path.strip():
        raise RasterError("A raster path is required.")
    if not os.path.exists(path):
        raise RasterError(f"Raster file not found: {path}")

    # A multi-file scene is assembled by opening each band through this same
    # function, so both backends and the sidecar apply to every band.
    if os.path.isdir(path):
        return open_scene_directory(path, _open_single_raster)
    if is_scene_manifest(path):
        return open_scene(path, _open_single_raster)

    return _open_single_raster(path, band_names)


def _open_single_raster(
    path: str, band_names: list[str] | None = None
) -> RasterDataset:
    """Open exactly one raster file."""
    if os.path.getsize(path) == 0:
        raise RasterError(f"Raster file is empty: {path}")

    sidecar = _read_sidecar(path)
    names = band_names or sidecar.get("band_names")

    if has_rasterio():
        try:
            dataset = _open_with_rasterio(path, names)
        except RasterError:
            raise
        except Exception as error:
            # Keep every backend failure inside the project's error hierarchy,
            # so callers only ever have to catch RasterError.
            raise UnsupportedRasterError(
                f"Could not read '{path}' with the rasterio backend: {error}"
            ) from error
    else:
        extension = os.path.splitext(path)[1].lower()
        if extension not in GEOTIFF_EXTENSIONS and not tiff.is_tiff(path):
            raise UnsupportedRasterError(
                f"Cannot read '{path}' with the built-in backend. Install rasterio "
                "(pip install rasterio) to read this format, or supply a GeoTIFF."
            )
        dataset = tiff.read_tiff(path, names)

    dataset.metadata.update(sidecar)
    dataset.metadata.setdefault("backend", active_backend())
    return dataset


def _open_with_rasterio(path: str, band_names: list[str] | None) -> RasterDataset:
    import numpy
    import rasterio

    with rasterio.open(path) as source:
        names = band_names or [
            source.descriptions[index] or f"B{index + 1}"
            for index in range(source.count)
        ]
        if len(names) != source.count:
            raise RasterError(
                f"{path} contains {source.count} band(s) but {len(names)} name(s) "
                "were supplied."
            )

        dtype = str(source.dtypes[0])
        nodata = source.nodata
        bands = [
            BandArray(
                name=names[index],
                width=source.width,
                height=source.height,
                values=source.read(index + 1).reshape(-1),
                dtype=str(source.dtypes[index]),
                nodata=nodata,
            )
            for index in range(source.count)
        ]

        transform = source.transform
        georeference = GeoReference(
            crs=str(source.crs) if source.crs else None,
            transform=(
                transform.c, transform.a, transform.b,
                transform.f, transform.d, transform.e,
            ),
        )
        metadata: dict[str, Any] = dict(source.tags() or {})

    numpy  # imported to guarantee array support is present alongside rasterio
    return RasterDataset(
        width=bands[0].width,
        height=bands[0].height,
        bands=bands,
        georeference=georeference,
        dtype=dtype,
        nodata=nodata,
        path=path,
        metadata=metadata,
    )


# ============================================================
# WRITING
# ============================================================
def write_raster(
    path: str,
    bands: list[BandArray],
    georeference: GeoReference | None = None,
    dtype: str | None = None,
    nodata: float | None = None,
    compress: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Write bands to a GeoTIFF using the active backend.

    Band names and ``metadata`` (the sensor, for instance) are written *into*
    the file by both backends, so a raster stays self-describing when it is
    uploaded, copied, or handed to other software. The JSON sidecar remains
    supported for products that arrive without that information.

    Validation happens here rather than inside a backend so that both backends
    accept and reject exactly the same inputs. GDAL, for instance, will happily
    write dtypes the built-in codec cannot read back.

    Output is **uncompressed by default**, deliberately. A compressed GeoTIFF
    can only be read back with rasterio, which would mean a machine that later
    loses GDAL could not open rasters this project itself produced. Pass
    ``compress="deflate"`` to opt into compression when the size of a full
    scene matters more than that portability.
    """
    if not bands:
        raise RasterError("At least one band is required to write a raster.")

    width, height = bands[0].width, bands[0].height
    for band in bands:
        if (band.width, band.height) != (width, height):
            raise RasterError(
                f"All bands written to one raster must share a grid, but "
                f"'{bands[0].name}' is {width}x{height} and '{band.name}' is "
                f"{band.width}x{band.height}."
            )

    dtype = dtype or bands[0].dtype
    if dtype not in DTYPE_TO_TYPECODE:
        raise UnsupportedRasterError(
            f"Cannot write raster samples of dtype '{dtype}'. Supported dtypes: "
            f"{sorted(DTYPE_TO_TYPECODE)}."
        )

    if compress and not has_rasterio():
        raise UnsupportedRasterError(
            f"Compression '{compress}' requires rasterio; the built-in codec "
            "writes uncompressed GeoTIFF only."
        )

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    try:
        if has_rasterio():
            return _write_with_rasterio(
                path, bands, georeference, dtype, nodata, compress, metadata
            )
        return tiff.write_tiff(path, bands, georeference, dtype, nodata, metadata)
    except RasterError:
        raise
    except Exception as error:
        raise RasterError(f"Could not write raster '{path}': {error}") from error


def _write_with_rasterio(
    path: str,
    bands: list[BandArray],
    georeference: GeoReference | None,
    dtype: str | None,
    nodata: float | None,
    compress: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    import numpy
    import rasterio
    from rasterio.transform import Affine

    dtype = dtype or bands[0].dtype
    height, width = bands[0].height, bands[0].width

    transform = None
    if georeference and georeference.transform:
        origin_x, pixel_width, row_rotation, origin_y, column_rotation, pixel_height = (
            georeference.transform
        )
        transform = Affine(
            pixel_width, row_rotation, origin_x,
            column_rotation, pixel_height, origin_y,
        )

    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": len(bands),
        "dtype": dtype,
    }
    if compress:
        profile["compress"] = compress
    if transform is not None:
        profile["transform"] = transform
    if georeference and georeference.crs:
        profile["crs"] = georeference.crs
    if nodata is not None:
        profile["nodata"] = nodata

    with rasterio.open(path, "w", **profile) as destination:
        for index, band in enumerate(bands):
            data = numpy.asarray(band.values, dtype=dtype).reshape(height, width)
            destination.write(data, index + 1)
            destination.set_band_description(index + 1, band.name)
        tags = {
            key: str(value)
            for key, value in (metadata or {}).items()
            if value is not None and key != "band_names"
        }
        if tags:
            destination.update_tags(**tags)

    return path
