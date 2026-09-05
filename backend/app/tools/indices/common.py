"""Normalised difference index arithmetic shared by NDVI, NDWI and NDBI.

Every index in this family has the same form::

    index = (a - b) / (a + b)

so the arithmetic, the nodata handling and the statistics live here once, and
each index module only declares which bands play the roles of ``a`` and ``b``.

Two correctness details drive most of this code:

*Nodata and division by zero.* Satellite rasters are full of masked pixels
(cloud masks, scene edges, fill values). A pixel is only computed when both
inputs are valid *and* their sum is non-zero; everything else is written as
nodata rather than as a misleading number.

*Offsets change the answer, scales do not.* A normalised difference is
invariant under a shared multiplicative scale, so converting DN to reflectance
by dividing by 10000 leaves the index unchanged. An additive offset is *not*
invariant -- Sentinel-2 processing baseline 04.00 introduced ``BOA_ADD_OFFSET``
of -1000, and ignoring it shifts the index. ``offset`` is therefore exposed and
applied before the difference is taken.
"""

from __future__ import annotations

import math
from typing import Any

from app.tools.base import ToolExecutionError
from app.tools.raster.backends import has_numpy
from app.tools.raster.model import BandArray, new_sample_buffer

#: Value written for pixels that cannot be computed.
NODATA = float("nan")


def _is_nodata(value: float, nodata: float | None) -> bool:
    if nodata is None:
        return False
    if math.isnan(nodata):
        return math.isnan(value)
    return value == nodata


def normalized_difference(
    band_a: BandArray,
    band_b: BandArray,
    name: str,
    scale: float = 1.0,
    offset: float = 0.0,
    nodata: float = NODATA,
    mask: Any = None,
) -> tuple[BandArray, dict[str, Any]]:
    """Compute ``(a - b) / (a + b)`` pixel-wise with full nodata handling.

    ``mask``, when given, is a per-pixel sequence that is falsy wherever the
    pixel must be excluded -- typically a cloud mask. Masked pixels become
    nodata and are left out of the statistics, so a cloudy scene reports a
    smaller valid fraction rather than a contaminated mean.

    Returns the resulting float32 band together with a statistics dictionary
    describing how many pixels were actually computable.
    """
    if (band_a.width, band_a.height) != (band_b.width, band_b.height):
        raise ToolExecutionError(
            f"Bands '{band_a.name}' ({band_a.width}x{band_a.height}) and "
            f"'{band_b.name}' ({band_b.width}x{band_b.height}) are on different "
            "grids. Resample them to a common grid before computing an index."
        )
    if scale == 0:
        raise ToolExecutionError("A band scale factor of zero is not meaningful.")

    if has_numpy():
        values, statistics = _compute_with_numpy(
            band_a, band_b, scale, offset, nodata, mask
        )
    else:
        values, statistics = _compute_with_stdlib(
            band_a, band_b, scale, offset, nodata, mask
        )

    result = BandArray(
        name=name,
        width=band_a.width,
        height=band_a.height,
        values=values,
        dtype="float32",
        nodata=nodata,
    )
    statistics["total_pixels"] = band_a.size
    statistics["valid_fraction"] = (
        statistics["valid_pixels"] / band_a.size if band_a.size else 0.0
    )
    return result, statistics


def _compute_with_numpy(
    band_a: BandArray,
    band_b: BandArray,
    scale: float,
    offset: float,
    nodata: float,
    mask: Any = None,
) -> tuple[Any, dict[str, Any]]:
    import numpy

    a = (numpy.asarray(band_a.values, dtype=numpy.float64) + offset) * scale
    b = (numpy.asarray(band_b.values, dtype=numpy.float64) + offset) * scale

    valid = numpy.isfinite(a) & numpy.isfinite(b)
    if band_a.nodata is not None:
        raw_a = numpy.asarray(band_a.values, dtype=numpy.float64)
        valid &= ~_nodata_mask(numpy, raw_a, band_a.nodata)
    if band_b.nodata is not None:
        raw_b = numpy.asarray(band_b.values, dtype=numpy.float64)
        valid &= ~_nodata_mask(numpy, raw_b, band_b.nodata)

    if mask is not None:
        valid &= numpy.asarray(mask, dtype=bool)

    denominator = a + b
    valid &= denominator != 0

    result = numpy.full(a.shape, nodata, dtype=numpy.float32)
    numpy.divide(a - b, denominator, out=result, where=valid, casting="unsafe")

    computed = result[valid]
    statistics = _summarise_numpy(numpy, computed)
    statistics["valid_pixels"] = int(valid.sum())
    statistics["nodata_pixels"] = int(a.size - valid.sum())
    return result, statistics


def _nodata_mask(numpy: Any, values: Any, nodata: float) -> Any:
    if math.isnan(nodata):
        return numpy.isnan(values)
    return values == nodata


#: Percentiles reported alongside the moments. The median is far more
#: informative than the mean on an index raster -- a handful of cloud or water
#: pixels drag the mean but not the median -- and the quartiles give a frontend
#: enough to draw a distribution without shipping the whole band.
PERCENTILES = (5.0, 25.0, 50.0, 75.0, 95.0)

_EMPTY_SUMMARY: dict[str, Any] = {
    "minimum": None,
    "maximum": None,
    "mean": None,
    "standard_deviation": None,
    "median": None,
    "percentiles": {},
}


def _percentile_key(percentile: float) -> str:
    return f"p{percentile:g}"


def _summarise_numpy(numpy: Any, computed: Any) -> dict[str, Any]:
    if computed.size == 0:
        return dict(_EMPTY_SUMMARY)
    # One partition pass for every percentile, rather than a sort per call.
    values = numpy.percentile(computed, PERCENTILES)
    percentiles = {
        _percentile_key(p): float(value) for p, value in zip(PERCENTILES, values)
    }
    return {
        "minimum": float(computed.min()),
        "maximum": float(computed.max()),
        "mean": float(computed.mean()),
        "standard_deviation": float(computed.std()),
        "median": percentiles[_percentile_key(50.0)],
        "percentiles": percentiles,
    }


def _percentiles_from_sorted(values: list[float]) -> dict[str, float]:
    """Linear-interpolation percentiles, matching numpy's default method.

    Used only on the dependency-free path, so both raster backends report the
    same statistics for the same input.
    """
    if not values:
        return {}
    last = len(values) - 1
    result: dict[str, float] = {}
    for percentile in PERCENTILES:
        position = (percentile / 100.0) * last
        lower = int(position)
        upper = min(lower + 1, last)
        weight = position - lower
        result[_percentile_key(percentile)] = (
            values[lower] * (1.0 - weight) + values[upper] * weight
        )
    return result


def _compute_with_stdlib(
    band_a: BandArray,
    band_b: BandArray,
    scale: float,
    offset: float,
    nodata: float,
    mask: Any = None,
) -> tuple[Any, dict[str, Any]]:
    size = band_a.size
    result = new_sample_buffer("float32", size, nodata)

    source_a = band_a.values
    source_b = band_b.values
    nodata_a = band_a.nodata
    nodata_b = band_b.nodata

    valid_count = 0
    total = 0.0
    total_squares = 0.0
    minimum = None
    maximum = None
    # Percentiles need the values themselves, not just running moments. Only
    # computed pixels are kept, so this holds the valid subset rather than the
    # whole raster.
    computed_values: list[float] = []

    for index in range(size):
        if mask is not None and not mask[index]:
            continue

        raw_a = source_a[index]
        raw_b = source_b[index]
        if _is_nodata(raw_a, nodata_a) or _is_nodata(raw_b, nodata_b):
            continue

        a = (raw_a + offset) * scale
        b = (raw_b + offset) * scale
        if not (math.isfinite(a) and math.isfinite(b)):
            continue

        denominator = a + b
        if denominator == 0:
            continue

        value = (a - b) / denominator
        result[index] = value

        valid_count += 1
        total += value
        total_squares += value * value
        computed_values.append(value)
        if minimum is None or value < minimum:
            minimum = value
        if maximum is None or value > maximum:
            maximum = value

    if valid_count:
        mean = total / valid_count
        variance = max(total_squares / valid_count - mean * mean, 0.0)
        percentiles = _percentiles_from_sorted(sorted(computed_values))
        statistics: dict[str, Any] = {
            "minimum": minimum,
            "maximum": maximum,
            "mean": mean,
            "standard_deviation": math.sqrt(variance),
            "median": percentiles.get(_percentile_key(50.0)),
            "percentiles": percentiles,
        }
    else:
        statistics = dict(_EMPTY_SUMMARY)

    statistics["valid_pixels"] = valid_count
    statistics["nodata_pixels"] = size - valid_count
    return result, statistics


def classify_ranges(
    band: BandArray,
    ranges: list[tuple[str, float, float]],
) -> dict[str, dict[str, Any]]:
    """Count valid pixels falling into each ``(label, lower, upper)`` range.

    Ranges are half-open ``[lower, upper)`` except the final one, which is
    closed so that the maximum value is counted.
    """
    counts = {label: 0 for label, _, _ in ranges}
    valid = 0

    if has_numpy():
        import numpy

        values = numpy.asarray(band.values, dtype=numpy.float64)
        mask = numpy.isfinite(values)
        if band.nodata is not None and not math.isnan(band.nodata):
            mask &= values != band.nodata
        valid = int(mask.sum())
        for index, (label, lower, upper) in enumerate(ranges):
            last = index == len(ranges) - 1
            within = mask & (values >= lower) & (
                (values <= upper) if last else (values < upper)
            )
            counts[label] = int(within.sum())
    else:
        for raw in band.values:
            value = float(raw)
            if not math.isfinite(value):
                continue
            if band.nodata is not None and not math.isnan(band.nodata):
                if value == band.nodata:
                    continue
            valid += 1
            for index, (label, lower, upper) in enumerate(ranges):
                last = index == len(ranges) - 1
                if lower <= value and (value <= upper if last else value < upper):
                    counts[label] += 1
                    break

    return {
        label: {
            "pixels": count,
            "fraction": (count / valid) if valid else 0.0,
        }
        for label, count in counts.items()
    }
