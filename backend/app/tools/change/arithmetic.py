"""Difference and thresholding arithmetic for bi-temporal change detection."""

from __future__ import annotations

import math
from typing import Any

from app.tools.base import ToolExecutionError
from app.tools.indices.common import NODATA
from app.tools.raster.backends import has_numpy
from app.tools.raster.model import BandArray, new_sample_buffer

#: Change classification codes written into the output raster.
CLASS_NODATA = 0
CLASS_DECREASE = 1
CLASS_STABLE = 2
CLASS_INCREASE = 3

CLASS_LABELS = {
    CLASS_DECREASE: "decrease",
    CLASS_STABLE: "stable",
    CLASS_INCREASE: "increase",
}


def difference(later: BandArray, earlier: BandArray, name: str = "difference") -> tuple[BandArray, dict[str, Any]]:
    """Compute ``later - earlier`` where both dates are valid.

    A pixel that is nodata on either date stays nodata: a change value cannot
    be asserted for ground that was not observed twice.
    """
    if (later.width, later.height) != (earlier.width, earlier.height):
        raise ToolExecutionError(
            "Cannot difference bands on different grids "
            f"({later.width}x{later.height} and {earlier.width}x{earlier.height})."
        )

    if has_numpy():
        values, statistics = _difference_numpy(later, earlier)
    else:
        values, statistics = _difference_stdlib(later, earlier)

    band = BandArray(
        name=name,
        width=later.width,
        height=later.height,
        values=values,
        dtype="float32",
        nodata=NODATA,
    )
    statistics["total_pixels"] = later.size
    statistics["valid_fraction"] = (
        statistics["valid_pixels"] / later.size if later.size else 0.0
    )
    return band, statistics


def _difference_numpy(later: BandArray, earlier: BandArray):
    import numpy

    after = numpy.asarray(later.values, dtype=numpy.float64)
    before = numpy.asarray(earlier.values, dtype=numpy.float64)

    valid = numpy.isfinite(after) & numpy.isfinite(before)
    result = numpy.full(after.shape, NODATA, dtype=numpy.float32)
    numpy.subtract(after, before, out=result, where=valid, casting="unsafe")

    computed = result[valid]
    if computed.size:
        statistics = {
            "minimum": float(computed.min()),
            "maximum": float(computed.max()),
            "mean": float(computed.mean()),
            "standard_deviation": float(computed.std()),
        }
    else:
        statistics = {
            "minimum": None, "maximum": None,
            "mean": None, "standard_deviation": None,
        }
    statistics["valid_pixels"] = int(valid.sum())
    statistics["nodata_pixels"] = int(after.size - valid.sum())
    return result, statistics


def _difference_stdlib(later: BandArray, earlier: BandArray):
    size = later.size
    result = new_sample_buffer("float32", size, NODATA)

    count = 0
    total = 0.0
    total_squares = 0.0
    minimum = maximum = None

    for index in range(size):
        after = float(later.values[index])
        before = float(earlier.values[index])
        if not (math.isfinite(after) and math.isfinite(before)):
            continue

        value = after - before
        result[index] = value
        count += 1
        total += value
        total_squares += value * value
        if minimum is None or value < minimum:
            minimum = value
        if maximum is None or value > maximum:
            maximum = value

    if count:
        mean = total / count
        variance = max(total_squares / count - mean * mean, 0.0)
        statistics: dict[str, Any] = {
            "minimum": minimum, "maximum": maximum,
            "mean": mean, "standard_deviation": math.sqrt(variance),
        }
    else:
        statistics = {
            "minimum": None, "maximum": None,
            "mean": None, "standard_deviation": None,
        }
    statistics["valid_pixels"] = count
    statistics["nodata_pixels"] = size - count
    return result, statistics


def resolve_threshold(
    statistics: dict[str, Any],
    method: str,
    fixed: float,
    sigma_multiplier: float,
) -> tuple[float, str]:
    """Decide the magnitude above which a difference counts as change.

    ``fixed`` applies one absolute cut-off, which is reproducible across scenes
    and is the right choice when comparing results between areas. ``statistical``
    derives the cut-off from the scene's own variability, which adapts to noisy
    imagery but makes two scenes' outputs incomparable. Neither is universally
    correct, so the choice is explicit and is reported alongside the result.
    """
    method = str(method).strip().lower()

    if method == "fixed":
        if fixed <= 0:
            raise ToolExecutionError("A fixed change threshold must be positive.")
        return fixed, f"fixed threshold of {fixed:g}"

    if method == "statistical":
        deviation = statistics.get("standard_deviation")
        if not deviation:
            raise ToolExecutionError(
                "A statistical threshold needs a non-zero spread in the difference "
                "image, but the differences have no variation. Use "
                "threshold_method='fixed' for this pair."
            )
        if sigma_multiplier <= 0:
            raise ToolExecutionError("sigma_multiplier must be positive.")
        threshold = sigma_multiplier * deviation
        return threshold, (
            f"{sigma_multiplier:g} standard deviations of the difference image "
            f"({threshold:.4f})"
        )

    raise ToolExecutionError(
        f"Unknown threshold_method '{method}'. Use 'fixed' or 'statistical'."
    )


def classify_change(
    band: BandArray,
    threshold: float,
) -> tuple[BandArray, dict[str, int]]:
    """Split a difference band into decrease, stable and increase classes."""
    if has_numpy():
        import numpy

        values = numpy.asarray(band.values, dtype=numpy.float64)
        valid = numpy.isfinite(values)

        codes = numpy.full(values.shape, CLASS_NODATA, dtype=numpy.uint8)
        codes[valid & (values <= -threshold)] = CLASS_DECREASE
        codes[valid & (numpy.abs(values) < threshold)] = CLASS_STABLE
        codes[valid & (values >= threshold)] = CLASS_INCREASE

        counts = {
            label: int((codes == code).sum()) for code, label in CLASS_LABELS.items()
        }
    else:
        codes = new_sample_buffer("uint8", band.size, CLASS_NODATA)
        counts = {label: 0 for label in CLASS_LABELS.values()}
        for index in range(band.size):
            value = float(band.values[index])
            if not math.isfinite(value):
                continue
            if value <= -threshold:
                code = CLASS_DECREASE
            elif value >= threshold:
                code = CLASS_INCREASE
            else:
                code = CLASS_STABLE
            codes[index] = code
            counts[CLASS_LABELS[code]] += 1

    classification = BandArray(
        name="change_class",
        width=band.width,
        height=band.height,
        values=codes,
        dtype="uint8",
        nodata=float(CLASS_NODATA),
    )
    return classification, counts
