"""Backscatter arithmetic for synthetic aperture radar.

Three operations, each with a correctness trap that this module exists to
avoid:

*Units.* Calibrated backscatter arrives either as linear power (sigma0, gamma0)
or already in decibels. Thresholds are published in decibels, so linear power
is converted with ``10 * log10``; converting a dB image a second time would
produce nonsense that still looks like a map. ``input_units="auto"`` decides
from the data itself -- a dB image has a negative median, linear power cannot
-- and refuses integer digital numbers outright, because an uncalibrated
product has no meaningful threshold at all.

*Speckle.* Radar images carry multiplicative speckle, so single-pixel
thresholds produce salt-and-pepper maps. The optional boxcar filter averages
*linear power*, never decibels: the mean of logarithms is not the logarithm of
the mean, and averaging dB biases every value low.

*Thresholds.* A fixed decibel threshold is reproducible across scenes. Otsu's
method adapts to the scene by splitting its histogram where the between-class
variance peaks, which suits a scene that genuinely contains both water and
land and misleads on one that does not. The choice is explicit and reported.
"""

from __future__ import annotations

import math
from typing import Any

from app.tools.base import ToolExecutionError
from app.tools.raster.backends import has_numpy
from app.tools.raster.bands import normalise
from app.tools.raster.model import BandArray, RasterDataset, new_sample_buffer

#: Polarisation channels, in the order they are preferred for water mapping.
#: Co-polarised channels separate smooth water from land most cleanly. RH and
#: RV are RISAT-1's compact-polarimetry channels.
POLARISATION_PREFERENCE = ("vv", "hh", "vh", "hv", "rh", "rv")

#: Published starting points for open-water thresholds, in dB. Cross-polarised
#: returns are weaker overall, so their water threshold sits lower. For the
#: compact-pol channels there is no settled published value; they start at the
#: co-pol threshold, and threshold_method="otsu" is the better choice for them.
DEFAULT_WATER_THRESHOLD_DB = {
    "vv": -18.0, "hh": -18.0, "vh": -24.0, "hv": -24.0, "rh": -18.0, "rv": -18.0,
}

#: Histogram range for Otsu's method. Values outside it are noise floor or
#: strong point targets and would only distort the split.
OTSU_RANGE_DB = (-40.0, 10.0)
OTSU_BINS = 256

INTEGER_DTYPES = {"uint8", "int8", "uint16", "int16", "uint32", "int32"}

#: Class codes written into the water map. 0 is nodata.
CLASS_NODATA = 0
WATER = 1
NON_WATER = 2
CLASS_LABELS = {WATER: "water", NON_WATER: "non_water"}


def resolve_polarisation(dataset: RasterDataset, requested: str | None) -> BandArray:
    """Return the band carrying the requested polarisation.

    Without a request, the first available of VV, HH, VH, HV is used.
    """
    bands = {normalise(band.name): band for band in dataset.bands}
    if requested:
        key = normalise(str(requested))
        if key in bands:
            return bands[key]
        raise ToolExecutionError(
            f"Polarisation '{requested}' is not present in the scene. Available "
            f"bands: {dataset.band_names}."
        )
    for polarisation in POLARISATION_PREFERENCE:
        if polarisation in bands:
            return bands[polarisation]
    raise ToolExecutionError(
        "No SAR polarisation band (VV, VH, HH or HV) was found. Available bands: "
        f"{dataset.band_names}. Name the band holding backscatter with the "
        "'polarisation' parameter."
    )


def _valid_samples(band: BandArray) -> list[float]:
    nodata = band.nodata
    samples = []
    for raw in band.values:
        value = float(raw)
        if not math.isfinite(value):
            continue
        if nodata is not None and not math.isnan(nodata) and value == nodata:
            continue
        samples.append(value)
    return samples


def detect_units(band: BandArray) -> str:
    """Decide whether ``band`` holds linear power or decibels.

    Raises when the samples look like uncalibrated digital numbers.
    """
    if has_numpy():
        import numpy

        values = numpy.asarray(band.values, dtype=numpy.float64)
        valid = numpy.isfinite(values)
        if band.nodata is not None and not math.isnan(band.nodata):
            valid &= values != band.nodata
        samples = values[valid]
        if samples.size == 0:
            raise ToolExecutionError("The SAR band has no valid samples.")
        median = float(numpy.median(samples))
        high = float(numpy.percentile(samples, 95))
    else:
        samples = sorted(_valid_samples(band))
        if not samples:
            raise ToolExecutionError("The SAR band has no valid samples.")
        median = samples[len(samples) // 2]
        high = samples[min(len(samples) - 1, int(0.95 * (len(samples) - 1)))]

    if median < 0:
        return "db"
    if band.dtype in INTEGER_DTYPES or high > 50:
        raise ToolExecutionError(
            f"Band '{band.name}' looks like uncalibrated digital numbers "
            f"({band.dtype}, 95th percentile {high:g}). Water thresholds are "
            "defined on calibrated backscatter: supply sigma0 or gamma0 in linear "
            "power or in dB, or set input_units explicitly."
        )
    return "linear"


def to_linear_power(band: BandArray, units: str) -> tuple[Any, Any]:
    """Return ``(power, valid)`` as flat sequences of linear power and validity."""
    if units not in {"db", "linear"}:
        raise ToolExecutionError(f"Unknown input_units '{units}'. Use 'auto', 'db' or 'linear'.")

    if has_numpy():
        import numpy

        values = numpy.asarray(band.values, dtype=numpy.float64)
        valid = numpy.isfinite(values)
        if band.nodata is not None:
            valid &= ~(
                numpy.isnan(values) if math.isnan(band.nodata) else values == band.nodata
            )
        if units == "db":
            power = numpy.where(valid, numpy.power(10.0, values / 10.0), numpy.nan)
        else:
            # log10 of zero or negative power is undefined: those pixels are
            # nodata, not "very dark water".
            valid &= values > 0
            power = numpy.where(valid, values, numpy.nan)
        return power, valid

    power = [float("nan")] * band.size
    valid = [False] * band.size
    for index, raw in enumerate(band.values):
        value = float(raw)
        if not math.isfinite(value):
            continue
        if band.nodata is not None and not math.isnan(band.nodata) and value == band.nodata:
            continue
        if units == "db":
            power[index] = 10.0 ** (value / 10.0)
        elif value > 0:
            power[index] = value
        else:
            continue
        valid[index] = True
    return power, valid


def boxcar(power: Any, valid: Any, width: int, height: int, window: int) -> Any:
    """Mean of the valid linear-power samples in a ``window`` x ``window`` box.

    Computed with summed-area tables, so the cost does not grow with the
    window. Nodata neighbours are excluded from the mean rather than counted as
    zero, so a coastline next to a nodata strip is not darkened into water.
    """
    if window < 3 or window % 2 == 0 or window > 31:
        raise ToolExecutionError("filter_window must be an odd integer between 3 and 31.")
    radius = window // 2

    if has_numpy():
        import numpy

        grid = numpy.where(valid, power, 0.0).reshape(height, width)
        counts = numpy.asarray(valid, dtype=numpy.float64).reshape(height, width)

        def summed(values):
            table = numpy.zeros((height + 1, width + 1), dtype=numpy.float64)
            table[1:, 1:] = values.cumsum(axis=0).cumsum(axis=1)
            return table

        sums, numbers = summed(grid), summed(counts)
        rows = numpy.arange(height)
        cols = numpy.arange(width)
        top = numpy.clip(rows - radius, 0, height)[:, None]
        bottom = numpy.clip(rows + radius + 1, 0, height)[:, None]
        left = numpy.clip(cols - radius, 0, width)[None, :]
        right = numpy.clip(cols + radius + 1, 0, width)[None, :]

        def window_total(table):
            return table[bottom, right] - table[top, right] - table[bottom, left] + table[top, left]

        total, number = window_total(sums), window_total(numbers)
        with numpy.errstate(divide="ignore", invalid="ignore"):
            smoothed = numpy.where(number > 0, total / numpy.where(number > 0, number, 1), numpy.nan)
        return numpy.where(numpy.asarray(valid).reshape(height, width), smoothed, numpy.nan).reshape(-1)

    def summed_list(values):
        table = [[0.0] * (width + 1) for _ in range(height + 1)]
        for row in range(height):
            running = 0.0
            for col in range(width):
                running += values[row * width + col]
                table[row + 1][col + 1] = table[row][col + 1] + running
        return table

    sums = summed_list([power[i] if valid[i] else 0.0 for i in range(width * height)])
    numbers = summed_list([1.0 if valid[i] else 0.0 for i in range(width * height)])
    smoothed = [float("nan")] * (width * height)
    for row in range(height):
        top, bottom = max(0, row - radius), min(height, row + radius + 1)
        for col in range(width):
            index = row * width + col
            if not valid[index]:
                continue
            left, right = max(0, col - radius), min(width, col + radius + 1)
            total = sums[bottom][right] - sums[top][right] - sums[bottom][left] + sums[top][left]
            number = numbers[bottom][right] - numbers[top][right] - numbers[bottom][left] + numbers[top][left]
            smoothed[index] = total / number
    return smoothed


def to_decibels(power: Any, valid: Any) -> Any:
    """Convert linear power to dB, leaving invalid pixels NaN."""
    if has_numpy():
        import numpy

        with numpy.errstate(divide="ignore", invalid="ignore"):
            return numpy.where(valid, 10.0 * numpy.log10(power), numpy.nan)
    return [
        10.0 * math.log10(value) if ok and value > 0 else float("nan")
        for value, ok in zip(power, valid)
    ]


def otsu_threshold(decibels: Any, valid: Any) -> float:
    """Otsu's threshold on the valid dB values inside :data:`OTSU_RANGE_DB`."""
    low, high = OTSU_RANGE_DB
    histogram = [0] * OTSU_BINS
    width = (high - low) / OTSU_BINS

    if has_numpy():
        import numpy

        values = numpy.asarray(decibels, dtype=numpy.float64)[numpy.asarray(valid, dtype=bool)]
        values = values[numpy.isfinite(values)]
        counts, _ = numpy.histogram(values, bins=OTSU_BINS, range=OTSU_RANGE_DB)
        histogram = [int(count) for count in counts]
    else:
        for value, ok in zip(decibels, valid):
            if not ok or not math.isfinite(value) or not low <= value <= high:
                continue
            slot = min(OTSU_BINS - 1, int((value - low) / width))
            histogram[slot] += 1

    total = sum(histogram)
    if total == 0:
        raise ToolExecutionError(
            f"No backscatter values fall within {low:g} to {high:g} dB, so Otsu's "
            "threshold cannot be computed. Use threshold_method='fixed'."
        )

    centres = [low + (index + 0.5) * width for index in range(OTSU_BINS)]
    grand = sum(count * centre for count, centre in zip(histogram, centres))
    best_variance, best_index = -1.0, 0
    weight = 0
    running = 0.0
    for index, count in enumerate(histogram):
        weight += count
        if weight == 0:
            continue
        remainder = total - weight
        if remainder == 0:
            break
        running += count * centres[index]
        mean_low = running / weight
        mean_high = (grand - running) / remainder
        variance = weight * remainder * (mean_low - mean_high) ** 2
        if variance > best_variance:
            best_variance, best_index = variance, index
    if best_variance <= 0:
        raise ToolExecutionError(
            "The backscatter histogram has no spread to split, so Otsu's threshold "
            "is undefined for this scene. Use threshold_method='fixed'."
        )
    return low + (best_index + 1) * width


def classify_water(
    decibels: Any, valid: Any, threshold: float, width: int, height: int
) -> tuple[BandArray, dict[str, int]]:
    """Label pixels below ``threshold`` dB as water (1) and the rest land (2)."""
    if has_numpy():
        import numpy

        values = numpy.asarray(decibels, dtype=numpy.float64)
        ok = numpy.asarray(valid, dtype=bool) & numpy.isfinite(values)
        codes = numpy.zeros(values.shape, dtype=numpy.uint8)
        codes[ok & (values < threshold)] = WATER
        codes[ok & (values >= threshold)] = NON_WATER
        counts = {
            "water": int((codes == WATER).sum()),
            "non_water": int((codes == NON_WATER).sum()),
        }
    else:
        codes = new_sample_buffer("uint8", width * height, CLASS_NODATA)
        counts = {"water": 0, "non_water": 0}
        for index, (value, ok) in enumerate(zip(decibels, valid)):
            if not ok or not math.isfinite(value):
                continue
            if value < threshold:
                codes[index] = WATER
                counts["water"] += 1
            else:
                codes[index] = NON_WATER
                counts["non_water"] += 1

    band = BandArray(
        name="sar_water",
        width=width,
        height=height,
        values=codes,
        dtype="uint8",
        nodata=float(CLASS_NODATA),
    )
    return band, counts


def summarise_decibels(decibels: Any, valid: Any) -> dict[str, Any]:
    """Moments and percentiles of the valid dB values."""
    if has_numpy():
        import numpy

        values = numpy.asarray(decibels, dtype=numpy.float64)
        values = values[numpy.asarray(valid, dtype=bool) & numpy.isfinite(values)]
        if values.size == 0:
            return {"minimum": None, "maximum": None, "mean": None, "median": None,
                    "standard_deviation": None, "percentiles": {}}
        points = numpy.percentile(values, (5, 25, 50, 75, 95))
        percentiles = {f"p{p}": float(v) for p, v in zip((5, 25, 50, 75, 95), points)}
        return {
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "mean": float(values.mean()),
            "median": percentiles["p50"],
            "standard_deviation": float(values.std()),
            "percentiles": percentiles,
        }

    values = sorted(
        value for value, ok in zip(decibels, valid) if ok and math.isfinite(value)
    )
    if not values:
        return {"minimum": None, "maximum": None, "mean": None, "median": None,
                "standard_deviation": None, "percentiles": {}}
    last = len(values) - 1

    def percentile(p: float) -> float:
        position = p / 100.0 * last
        lower = int(position)
        upper = min(lower + 1, last)
        return values[lower] * (1 - (position - lower)) + values[upper] * (position - lower)

    mean = sum(values) / len(values)
    percentiles = {f"p{p}": percentile(p) for p in (5, 25, 50, 75, 95)}
    return {
        "minimum": values[0],
        "maximum": values[-1],
        "mean": mean,
        "median": percentiles["p50"],
        "standard_deviation": math.sqrt(
            max(sum(v * v for v in values) / len(values) - mean * mean, 0.0)
        ),
        "percentiles": percentiles,
    }


def decibel_band(decibels: Any, width: int, height: int, name: str) -> BandArray:
    """Wrap dB values as a float32 band with NaN nodata, for writing."""
    if has_numpy():
        import numpy

        values = numpy.asarray(decibels, dtype=numpy.float32)
    else:
        values = new_sample_buffer("float32", width * height, float("nan"))
        for index, value in enumerate(decibels):
            values[index] = value
    return BandArray(
        name=name, width=width, height=height, values=values,
        dtype="float32", nodata=float("nan"),
    )



def calibrated_decibels(
    band: BandArray,
    width: int,
    height: int,
    units: str = "auto",
    speckle_filter: str = "none",
    window: int = 3,
) -> tuple[Any, Any, str]:
    """Return ``(decibels, valid, units_read_as)`` for one polarisation band.

    The shared path for every SAR measurement: read the units (or detect
    them), move to linear power, filter speckle there if asked, then convert
    to dB.
    """
    resolved = detect_units(band) if units == "auto" else units
    power, valid = to_linear_power(band, resolved)
    if speckle_filter == "boxcar":
        power = boxcar(power, valid, width, height, window)
    elif speckle_filter != "none":
        raise ToolExecutionError(
            f"Unknown speckle_filter '{speckle_filter}'. Use 'none' or 'boxcar'."
        )
    return to_decibels(power, valid), valid, resolved


def is_sar(dataset: RasterDataset) -> bool:
    """Whether ``dataset`` carries at least one SAR polarisation band."""
    return any(normalise(band.name) in POLARISATION_PREFERENCE for band in dataset.bands)
