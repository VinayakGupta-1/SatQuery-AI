"""Where in a scene a class is: the grounding behind every finding.

"12% of the scene is water" is an answer; "12% of the scene is water, centred
on the north-east at 21.84 N, 79.12 E" is one a person can act on. For each
class of a class raster this computes the centroid of its pixels, the part of
the scene that centroid falls in (a 3x3 compass grid), the class's extent, and
-- when the raster is georeferenced -- the centroid in longitude and latitude.

Every value is a plain statistic of the pixels, so a finding built from it can
be checked against the raster by anyone.
"""

from __future__ import annotations

from typing import Any

from app.tools.raster.backends import has_numpy
from app.tools.raster.model import BandArray, RasterDataset


def sector(col_fraction: float, row_fraction: float) -> str:
    """The part of the scene a point falls in, on a 3x3 compass grid."""
    vertical = "north" if row_fraction < 1 / 3 else "south" if row_fraction > 2 / 3 else ""
    horizontal = "west" if col_fraction < 1 / 3 else "east" if col_fraction > 2 / 3 else ""
    if vertical and horizontal:
        return f"{vertical}-{horizontal}"
    return vertical or horizontal or "centre"


def _accumulate(codes: Any, width: int, height: int, wanted: set[int]) -> dict[int, list[float]]:
    """Per code: ``[pixels, row_sum, col_sum, row_min, row_max, col_min, col_max]``."""
    totals: dict[int, list[float]] = {}
    if has_numpy():
        import numpy

        grid = numpy.asarray(codes).reshape(height, width)
        rows = numpy.arange(height, dtype=numpy.float64)
        cols = numpy.arange(width, dtype=numpy.float64)
        for code in wanted:
            mask = grid == code
            count = int(mask.sum())
            if not count:
                continue
            per_row = mask.sum(axis=1)
            per_col = mask.sum(axis=0)
            present_rows = numpy.flatnonzero(per_row)
            present_cols = numpy.flatnonzero(per_col)
            totals[code] = [
                count,
                float((per_row * rows).sum()),
                float((per_col * cols).sum()),
                int(present_rows[0]), int(present_rows[-1]),
                int(present_cols[0]), int(present_cols[-1]),
            ]
        return totals

    for index, value in enumerate(codes):
        code = int(value)
        if code not in wanted:
            continue
        row, col = divmod(index, width)
        entry = totals.get(code)
        if entry is None:
            totals[code] = [1, row, col, row, row, col, col]
            continue
        entry[0] += 1
        entry[1] += row
        entry[2] += col
        entry[3] = min(entry[3], row)
        entry[4] = max(entry[4], row)
        entry[5] = min(entry[5], col)
        entry[6] = max(entry[6], col)
    return totals


def class_locations(
    codes: Any, labels: dict[int, str], dataset: RasterDataset
) -> dict[str, dict[str, Any]]:
    """Where each labelled class of ``codes`` lies in ``dataset``'s scene."""
    from app.tools.raster.aoi import pixel_to_lonlat

    width, height = dataset.width, dataset.height
    totals = _accumulate(codes, width, height, set(labels))
    located: dict[str, dict[str, Any]] = {}
    for code, (pixels, row_sum, col_sum, r0, r1, c0, c1) in totals.items():
        col, row = col_sum / pixels, row_sum / pixels
        entry: dict[str, Any] = {
            "pixels": int(pixels),
            "centroid_pixel": [round(col, 2), round(row, 2)],
            "extent_pixels": [int(c0), int(r0), int(c1), int(r1)],
            "sector": sector((col + 0.5) / width, (row + 0.5) / height),
            # A class whose extent spans nearly the whole scene has no single
            # place; saying "centred on the south" would mislead.
            "widespread": (c1 - c0 + 1) >= 0.9 * width and (r1 - r0 + 1) >= 0.9 * height,
        }
        lonlat = pixel_to_lonlat(dataset, col, row)
        if lonlat is not None:
            entry["centroid_lonlat"] = [round(lonlat[0], 5), round(lonlat[1], 5)]
        located[labels[code]] = entry
    return located


def range_locations(
    band: BandArray,
    ranges: list[tuple[str, float, float]],
    dataset: RasterDataset,
) -> dict[str, dict[str, Any]]:
    """Where each ``(label, lower, upper)`` value range of ``band`` lies.

    Ranges are half-open except the last, matching how index classes are
    counted, so the pixels located here are exactly the pixels counted there.
    """
    codes = _range_codes(band, ranges)
    labels = {index + 1: label for index, (label, _, _) in enumerate(ranges)}
    return class_locations(codes, labels, dataset)


def _range_codes(band: BandArray, ranges: list[tuple[str, float, float]]) -> Any:
    import math

    if has_numpy():
        import numpy

        values = numpy.asarray(band.values, dtype=numpy.float64)
        valid = numpy.isfinite(values)
        if band.nodata is not None and not math.isnan(band.nodata):
            valid &= values != band.nodata
        codes = numpy.zeros(values.shape, dtype=numpy.uint8)
        for index, (_, lower, upper) in enumerate(ranges):
            last = index == len(ranges) - 1
            within = valid & (values >= lower) & ((values <= upper) if last else (values < upper))
            codes[within & (codes == 0)] = index + 1
        return codes

    codes = []
    for raw in band.values:
        value = float(raw)
        code = 0
        if math.isfinite(value) and not (
            band.nodata is not None and not math.isnan(band.nodata) and value == band.nodata
        ):
            for index, (_, lower, upper) in enumerate(ranges):
                last = index == len(ranges) - 1
                if lower <= value and (value <= upper if last else value < upper):
                    code = index + 1
                    break
        codes.append(code)
    return codes


__all__ = ["class_locations", "range_locations", "sector"]
