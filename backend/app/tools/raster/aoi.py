"""Areas of interest: clipping a raster to the part a question is about.

"How healthy is the vegetation in the north-west?" is a question about part of
a scene. Answering it over the whole scene would be a correct computation of
the wrong thing, so every tool clips its input here, before any arithmetic,
and reports exactly which window it analysed.

An area arrives as tool parameters -- flat, so the guard between a language
model and the tools can check them:

* ``aoi_region`` -- a named part of the scene (``north``, ``south_east``,
  ``centre`` ...), which needs no georeferencing;
* ``aoi_bbox`` and ``aoi_crs`` -- ``[min_x, min_y, max_x, max_y]``, longitude
  and latitude unless another CRS is named, which is transformed into the
  raster's own CRS and turned into a pixel window.

The window is snapped outward to whole pixels, so every pixel the area touches
is included; an area that misses the imagery entirely is refused.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.schemas.spatiotemporal import REGION_FRACTIONS, AreaOfInterest
from app.tools.base import ToolExecutionError
from app.tools.raster.backends import has_numpy
from app.tools.raster.crs import CRSError, WGS84, to_lonlat, transform_bounds
from app.tools.raster.io import open_raster
from app.tools.raster.model import (
    BandArray,
    GeoReference,
    RasterDataset,
    RasterError,
    new_sample_buffer,
)

_REGION_ALIASES = {
    "center": "centre",
    "middle": "centre",
    "northwest": "north_west",
    "northeast": "north_east",
    "southwest": "south_west",
    "southeast": "south_east",
}


@dataclass(frozen=True)
class Window:
    """A rectangle of pixels: first column and row, and its size."""

    col_off: int
    row_off: int
    width: int
    height: int


def area_from_parameters(parameters: dict[str, Any]) -> AreaOfInterest | None:
    """Read an area of interest from tool parameters, or ``None``."""
    bbox = parameters.get("aoi_bbox")
    if bbox not in (None, "", []):
        if isinstance(bbox, str):
            bbox = [part for part in bbox.replace(";", ",").split(",") if part.strip()]
        try:
            values = [float(value) for value in bbox]
        except (TypeError, ValueError) as error:
            raise ToolExecutionError(f"aoi_bbox must be four numbers, got {bbox!r}.") from error
        if len(values) != 4 or not all(math.isfinite(v) for v in values):
            raise ToolExecutionError(f"aoi_bbox must be four finite numbers, got {bbox!r}.")
        if not (values[0] < values[2] and values[1] < values[3]):
            raise ToolExecutionError(
                "aoi_bbox must be [min_x, min_y, max_x, max_y] with min below max."
            )
        return AreaOfInterest(bbox=values, crs=str(parameters.get("aoi_crs") or WGS84))

    region = parameters.get("aoi_region")
    if region not in (None, ""):
        key = str(region).strip().lower().replace("-", "_").replace(" ", "_")
        key = _REGION_ALIASES.get(key, key)
        if key not in REGION_FRACTIONS:
            raise ToolExecutionError(
                f"Unknown aoi_region '{region}'. Use one of {sorted(REGION_FRACTIONS)}."
            )
        return AreaOfInterest(region=key)
    return None


def window_for(dataset: RasterDataset, area: AreaOfInterest) -> Window:
    """The pixel window of ``dataset`` that ``area`` covers."""
    width, height = dataset.width, dataset.height
    if area.region:
        left, top, right, bottom = REGION_FRACTIONS[area.region]
        col0, col1 = math.floor(left * width), math.ceil(right * width)
        row0, row1 = math.floor(top * height), math.ceil(bottom * height)
        return Window(col0, row0, max(1, col1 - col0), max(1, row1 - row0))

    georeference = dataset.georeference
    transform = georeference.transform
    if not georeference.is_georeferenced or transform is None:
        raise ToolExecutionError(
            "The area of interest is given in coordinates, but the image has no "
            "georeferencing, so the area cannot be located in it."
        )
    origin_x, pixel_w, rot_x, origin_y, rot_y, pixel_h = transform
    if rot_x or rot_y:
        raise ToolExecutionError(
            "The image grid is rotated; clipping to coordinates needs a north-up grid."
        )

    try:
        min_x, min_y, max_x, max_y = transform_bounds(area.bbox, area.crs, georeference.crs)
    except CRSError as error:
        raise ToolExecutionError(str(error)) from error

    cols = sorted([(min_x - origin_x) / pixel_w, (max_x - origin_x) / pixel_w])
    rows = sorted([(max_y - origin_y) / pixel_h, (min_y - origin_y) / pixel_h])
    col0, col1 = max(0, math.floor(cols[0])), min(width, math.ceil(cols[1]))
    row0, row1 = max(0, math.floor(rows[0])), min(height, math.ceil(rows[1]))
    if col1 <= col0 or row1 <= row0:
        raise ToolExecutionError(
            f"The area of interest ({area.describe()}) does not overlap the image."
        )
    return Window(col0, row0, col1 - col0, row1 - row0)


def clip(dataset: RasterDataset, window: Window) -> RasterDataset:
    """A new dataset holding only ``window``, with its geotransform shifted."""
    c0, r0, w, h = window.col_off, window.row_off, window.width, window.height
    if (c0, r0, w, h) == (0, 0, dataset.width, dataset.height):
        return dataset

    bands: list[BandArray] = []
    for band in dataset.bands:
        if has_numpy():
            import numpy

            grid = numpy.asarray(band.values).reshape(dataset.height, dataset.width)
            values: Any = numpy.ascontiguousarray(grid[r0:r0 + h, c0:c0 + w]).reshape(-1)
        else:
            values = new_sample_buffer(band.dtype, w * h)
            for row in range(h):
                start = (r0 + row) * dataset.width + c0
                for col in range(w):
                    values[row * w + col] = band.values[start + col]
        bands.append(
            BandArray(
                name=band.name, width=w, height=h, values=values,
                dtype=band.dtype, nodata=band.nodata,
            )
        )

    transform = dataset.georeference.transform
    if transform is not None:
        origin_x, pixel_w, rot_x, origin_y, rot_y, pixel_h = transform
        transform = (
            origin_x + c0 * pixel_w + r0 * rot_x, pixel_w, rot_x,
            origin_y + c0 * rot_y + r0 * pixel_h, rot_y, pixel_h,
        )
    return RasterDataset(
        width=w,
        height=h,
        bands=bands,
        georeference=GeoReference(crs=dataset.georeference.crs, transform=transform),
        dtype=dataset.dtype,
        nodata=dataset.nodata,
        path=dataset.path,
        metadata=dict(dataset.metadata),
    )


def dataset_bounds(dataset: RasterDataset) -> list[float] | None:
    """``[min_x, min_y, max_x, max_y]`` in the dataset's CRS, if georeferenced."""
    transform = dataset.georeference.transform
    if not dataset.georeference.is_georeferenced or transform is None:
        return None
    origin_x, pixel_w, _, origin_y, _, pixel_h = transform
    far_x = origin_x + pixel_w * dataset.width
    far_y = origin_y + pixel_h * dataset.height
    return [min(origin_x, far_x), min(origin_y, far_y), max(origin_x, far_x), max(origin_y, far_y)]


def footprint_lonlat(dataset: RasterDataset) -> list[float] | None:
    """The dataset's extent as ``[west, south, east, north]`` in degrees."""
    bounds = dataset_bounds(dataset)
    if bounds is None:
        return None
    try:
        return transform_bounds(bounds, dataset.georeference.crs, WGS84)
    except CRSError:
        return None


def pixel_to_lonlat(dataset: RasterDataset, col: float, row: float) -> tuple[float, float] | None:
    """Longitude and latitude of the centre of pixel ``(col, row)``."""
    transform = dataset.georeference.transform
    if not dataset.georeference.is_georeferenced or transform is None:
        return None
    origin_x, pixel_w, rot_x, origin_y, rot_y, pixel_h = transform
    x = origin_x + (col + 0.5) * pixel_w + (row + 0.5) * rot_x
    y = origin_y + (col + 0.5) * rot_y + (row + 0.5) * pixel_h
    return to_lonlat(x, y, dataset.georeference.crs)


def apply_area(
    dataset: RasterDataset, parameters: dict[str, Any]
) -> tuple[RasterDataset, dict[str, Any] | None]:
    """Clip ``dataset`` to the area of interest in ``parameters``, if any."""
    area = area_from_parameters(parameters)
    if area is None:
        return dataset, None
    window = window_for(dataset, area)
    clipped = clip(dataset, window)
    return clipped, describe_clip(dataset, clipped, area, window)


def describe_clip(
    original: RasterDataset, clipped: RasterDataset, area: AreaOfInterest, window: Window
) -> dict[str, Any]:
    """What was analysed, for the result and the audit trail."""
    return {
        "area": area.describe(),
        "kind": "region" if area.region else "bbox",
        "window": {
            "col_off": window.col_off,
            "row_off": window.row_off,
            "width": window.width,
            "height": window.height,
        },
        "fraction_of_scene": (window.width * window.height)
        / float(original.width * original.height),
        "bounds": dataset_bounds(clipped),
        "bounds_lonlat": footprint_lonlat(clipped),
    }


def open_for_analysis(
    path: str, parameters: dict[str, Any]
) -> tuple[RasterDataset, dict[str, Any] | None]:
    """Open ``path`` and clip it to the requested area, in one step."""
    try:
        dataset = open_raster(path)
    except RasterError as error:
        raise ToolExecutionError(str(error)) from error
    return apply_area(dataset, parameters)


__all__ = [
    "Window",
    "apply_area",
    "area_from_parameters",
    "clip",
    "dataset_bounds",
    "describe_clip",
    "footprint_lonlat",
    "open_for_analysis",
    "pixel_to_lonlat",
    "window_for",
]
