"""Resampling a band onto another band's pixel grid.

Sentinel-2 delivers its bands at three resolutions -- red and NIR at 10 m,
SWIR at 20 m, aerosol and cirrus at 60 m. An index that mixes resolutions,
NDBI above all, cannot be computed until they share a grid.

Resampling is done by mapping each *target* pixel centre through the two
geotransforms into the source grid, rather than by scaling array indices. That
distinction matters: two rasters can have the same pixel size and still be
offset from one another, and only the geotransform reveals it.

Nearest-neighbour is the only method offered, deliberately. It replicates
measurements the sensor actually made instead of synthesising intermediate
radiometry, which keeps a computed index traceable to real observations. It
also behaves identically under both raster backends, so a result never depends
on which libraries happen to be installed.
"""

from __future__ import annotations

import math

from app.tools.raster.backends import has_numpy
from app.tools.raster.model import (
    BandArray,
    GeoReference,
    RasterError,
    new_sample_buffer,
)

NEAREST = "nearest"
SUPPORTED_METHODS = (NEAREST,)


def is_axis_aligned(georeference: GeoReference) -> bool:
    """Return True when a transform has no rotation or shear."""
    transform = georeference.transform
    if transform is None:
        return False
    return transform[2] == 0.0 and transform[4] == 0.0


def grids_match(
    first: GeoReference,
    first_shape: tuple[int, int],
    second: GeoReference,
    second_shape: tuple[int, int],
    tolerance: float = 1e-9,
) -> bool:
    """Return True when two grids are identical, so no resampling is needed."""
    if first_shape != second_shape:
        return False
    if first.transform is None or second.transform is None:
        return False
    return all(
        abs(a - b) <= tolerance * max(1.0, abs(a))
        for a, b in zip(first.transform, second.transform)
    )


def resample_band(
    band: BandArray,
    source: GeoReference,
    target: GeoReference,
    target_width: int,
    target_height: int,
    method: str = NEAREST,
    nodata: float | None = None,
) -> BandArray:
    """Sample ``band`` onto the grid described by ``target``.

    Target pixels that fall outside the source raster become ``nodata``; no
    value is extrapolated beyond the data that exists.
    """
    if method not in SUPPORTED_METHODS:
        raise RasterError(
            f"Unsupported resampling method '{method}'. Supported: "
            f"{list(SUPPORTED_METHODS)}."
        )
    if source.transform is None or target.transform is None:
        raise RasterError(
            "Both the source and the target must be georeferenced in order to "
            "resample between them."
        )
    if not is_axis_aligned(source) or not is_axis_aligned(target):
        raise RasterError(
            "Resampling supports north-up rasters only; this pair carries "
            "rotation or shear. Reproject it with GDAL first."
        )

    fill = band.nodata if nodata is None else nodata
    if fill is None:
        fill = float("nan")

    columns, rows = _source_indices(
        band, source, target, target_width, target_height
    )

    if has_numpy():
        values = _gather_numpy(band, columns, rows, target_width, target_height, fill)
    else:
        values = _gather_stdlib(band, columns, rows, target_width, target_height, fill)

    return BandArray(
        name=band.name,
        width=target_width,
        height=target_height,
        values=values,
        dtype=band.dtype if not math.isnan(fill) else band.dtype,
        nodata=fill,
    )


def _source_indices(
    band: BandArray,
    source: GeoReference,
    target: GeoReference,
    target_width: int,
    target_height: int,
):
    """Return the source column and row index for each target column and row.

    Because both grids are axis-aligned, the column mapping depends only on the
    target column and the row mapping only on the target row, so two small
    vectors describe the whole transformation.
    """
    source_x, source_pw, _, source_y, _, source_ph = source.transform
    target_x, target_pw, _, target_y, _, target_ph = target.transform

    def column_for(column: int) -> int:
        world = target_x + (column + 0.5) * target_pw
        return int(math.floor((world - source_x) / source_pw))

    def row_for(row: int) -> int:
        world = target_y + (row + 0.5) * target_ph
        return int(math.floor((world - source_y) / source_ph))

    return (
        [column_for(column) for column in range(target_width)],
        [row_for(row) for row in range(target_height)],
    )


def _gather_numpy(band, columns, rows, target_width, target_height, fill):
    import numpy

    source = numpy.asarray(band.values).reshape(band.height, band.width)
    column_index = numpy.asarray(columns, dtype=numpy.int64)
    row_index = numpy.asarray(rows, dtype=numpy.int64)

    column_valid = (column_index >= 0) & (column_index < band.width)
    row_valid = (row_index >= 0) & (row_index < band.height)

    gathered = source[
        numpy.clip(row_index, 0, band.height - 1)[:, None],
        numpy.clip(column_index, 0, band.width - 1)[None, :],
    ]

    inside = row_valid[:, None] & column_valid[None, :]
    if not inside.all():
        gathered = numpy.where(inside, gathered, fill)
    return numpy.asarray(gathered, dtype=source.dtype).reshape(-1)


def _gather_stdlib(band, columns, rows, target_width, target_height, fill):
    values = new_sample_buffer(band.dtype, target_width * target_height, 0)
    source = band.values

    for target_row in range(target_height):
        source_row = rows[target_row]
        base = target_row * target_width
        if not 0 <= source_row < band.height:
            for target_column in range(target_width):
                values[base + target_column] = _castable(fill, band.dtype)
            continue

        source_base = source_row * band.width
        for target_column in range(target_width):
            source_column = columns[target_column]
            if 0 <= source_column < band.width:
                values[base + target_column] = source[source_base + source_column]
            else:
                values[base + target_column] = _castable(fill, band.dtype)
    return values


def _castable(fill: float, dtype: str):
    """Coerce the fill value to something the buffer's dtype can hold."""
    if dtype.startswith("float"):
        return fill
    if math.isnan(fill):
        return 0
    return int(fill)
