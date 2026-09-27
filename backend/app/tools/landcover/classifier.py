"""Rule-based land-cover classification from spectral indices.

Every pixel is put into exactly one class by an ordered list of thresholds on
three published indices. The first rule that matches wins::

    1. water               NDWI >= 0.0      (McFeeters, 1996)
    2. dense_vegetation    NDVI >= 0.5
    3. sparse_vegetation   NDVI >= 0.2      (Rouse et al., 1974 breakpoints)
    4. built_up            NDBI >= 0.0      (Zha, Gao & Ni, 2003)   needs SWIR
    5. bare_soil           everything else                          needs SWIR

Without a SWIR band, NDBI cannot be computed, and nothing in the visible and
near-infrared separates bare ground from built-up surfaces reliably. Rules 4
and 5 then collapse into a single ``bare_or_built_up`` class rather than
splitting the two on a guess.

This is a transparent classifier, not a trained one. Its advantage is that
every label can be traced to two numbers and a threshold the user can see and
change; its limit is the known confusion between bare soil and built-up land
that NDBI alone cannot resolve. Both are reported with the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.tools.base import ToolExecutionError
from app.tools.raster.backends import has_numpy
from app.tools.raster.model import BandArray, new_sample_buffer

#: Class codes written into the output raster. 0 is reserved for nodata.
CLASS_NODATA = 0
WATER = 1
DENSE_VEGETATION = 2
SPARSE_VEGETATION = 3
BUILT_UP = 4
BARE_SOIL = 5
BARE_OR_BUILT_UP = 6

CLASS_LABELS: dict[int, str] = {
    WATER: "water",
    DENSE_VEGETATION: "dense_vegetation",
    SPARSE_VEGETATION: "sparse_vegetation",
    BUILT_UP: "built_up",
    BARE_SOIL: "bare_soil",
    BARE_OR_BUILT_UP: "bare_or_built_up",
}

#: The classes a scene can contain, depending on whether SWIR was available.
CODES_WITH_SWIR = (WATER, DENSE_VEGETATION, SPARSE_VEGETATION, BUILT_UP, BARE_SOIL)
CODES_WITHOUT_SWIR = (WATER, DENSE_VEGETATION, SPARSE_VEGETATION, BARE_OR_BUILT_UP)


@dataclass(frozen=True)
class Thresholds:
    """The breakpoints of the decision rules, in index units."""

    water: float = 0.0
    vegetation: float = 0.2
    dense_vegetation: float = 0.5
    built_up: float = 0.0

    def validate(self) -> "Thresholds":
        for name in ("water", "vegetation", "dense_vegetation", "built_up"):
            value = getattr(self, name)
            if not -1.0 <= value <= 1.0:
                raise ToolExecutionError(
                    f"The {name} threshold must lie in [-1, 1], the range of a "
                    f"normalised difference; got {value:g}."
                )
        if self.vegetation >= self.dense_vegetation:
            raise ToolExecutionError(
                "The vegetation threshold must be below the dense-vegetation "
                f"threshold ({self.vegetation:g} >= {self.dense_vegetation:g})."
            )
        return self

    def describe(self, has_swir: bool) -> list[str]:
        """The rules in the order they are applied, for the audit trail."""
        rules = [
            f"water: NDWI >= {self.water:g}",
            f"dense_vegetation: NDVI >= {self.dense_vegetation:g}",
            f"sparse_vegetation: NDVI >= {self.vegetation:g}",
        ]
        if has_swir:
            rules += [f"built_up: NDBI >= {self.built_up:g}", "bare_soil: otherwise"]
        else:
            rules += ["bare_or_built_up: otherwise (no SWIR band to separate them)"]
        return rules


@dataclass
class LandCoverResult:
    """The class raster and how many pixels fell into each class."""

    band: BandArray
    counts: dict[str, int]
    valid_pixels: int
    total_pixels: int
    has_swir: bool
    labels: list[str] = field(default_factory=list)


def classify_land_cover(
    green: BandArray,
    red: BandArray,
    nir: BandArray,
    swir: BandArray | None,
    thresholds: Thresholds,
    scale: float = 1.0,
    offset: float = 0.0,
    mask: Any = None,
) -> LandCoverResult:
    """Classify every pixel on the shared grid of the supplied bands.

    A pixel is classified only when every band it needs is valid and every
    index it needs is defined (a zero denominator leaves an index undefined).
    Anything else is written as ``CLASS_NODATA`` and left out of the counts,
    so an unobservable pixel never inflates a class.
    """
    bands = [green, red, nir] + ([swir] if swir is not None else [])
    width, height = green.width, green.height
    for band in bands:
        if (band.width, band.height) != (width, height):
            raise ToolExecutionError(
                f"Band '{band.name}' ({band.width}x{band.height}) is not on the "
                f"same grid as '{green.name}' ({width}x{height}). Resample the "
                "bands to a common grid before classifying."
            )
    if scale == 0:
        raise ToolExecutionError("A band scale factor of zero is not meaningful.")
    thresholds.validate()

    if has_numpy():
        codes = _classify_numpy(green, red, nir, swir, thresholds, scale, offset, mask)
    else:
        codes = _classify_stdlib(green, red, nir, swir, thresholds, scale, offset, mask)

    palette = CODES_WITH_SWIR if swir is not None else CODES_WITHOUT_SWIR
    counts = _count(codes, palette)
    band = BandArray(
        name="land_cover",
        width=width,
        height=height,
        values=codes,
        dtype="uint8",
        nodata=float(CLASS_NODATA),
    )
    return LandCoverResult(
        band=band,
        counts=counts,
        valid_pixels=sum(counts.values()),
        total_pixels=green.size,
        has_swir=swir is not None,
        labels=[CLASS_LABELS[code] for code in palette],
    )


def rule(ndvi: float, ndwi: float, ndbi: float | None, t: Thresholds) -> int:
    """Apply the decision rules to one pixel's indices.

    The vectorised path in :func:`_classify_numpy` applies the same rules in
    the same order; tests hold the two to identical output.
    """
    if ndwi >= t.water:
        return WATER
    if ndvi >= t.dense_vegetation:
        return DENSE_VEGETATION
    if ndvi >= t.vegetation:
        return SPARSE_VEGETATION
    if ndbi is None:
        return BARE_OR_BUILT_UP
    if ndbi >= t.built_up:
        return BUILT_UP
    return BARE_SOIL


# ============================================================
# BACKENDS
# ============================================================
def _classify_numpy(green, red, nir, swir, t, scale, offset, mask):
    import numpy

    def reflectance(band: BandArray):
        return (numpy.asarray(band.values, dtype=numpy.float64) + offset) * scale

    g, r, n = reflectance(green), reflectance(red), reflectance(nir)
    s = reflectance(swir) if swir is not None else None

    valid = numpy.ones(g.shape, dtype=bool)
    for band, values in ((green, g), (red, r), (nir, n), (swir, s)):
        if band is None:
            continue
        valid &= numpy.isfinite(values)
        if band.nodata is not None:
            raw = numpy.asarray(band.values, dtype=numpy.float64)
            valid &= ~(numpy.isnan(raw) if math.isnan(band.nodata) else raw == band.nodata)
    if mask is not None:
        valid &= numpy.asarray(mask, dtype=bool)

    valid &= (n + r) != 0
    valid &= (g + n) != 0
    if s is not None:
        valid &= (s + n) != 0

    with numpy.errstate(divide="ignore", invalid="ignore"):
        ndvi = (n - r) / numpy.where(valid, n + r, 1.0)
        ndwi = (g - n) / numpy.where(valid, g + n, 1.0)
        ndbi = (s - n) / numpy.where(valid, s + n, 1.0) if s is not None else None

    codes = numpy.full(g.shape, CLASS_NODATA, dtype=numpy.uint8)
    remaining = valid.copy()

    def assign(condition, code: int) -> None:
        selected = remaining & condition
        codes[selected] = code
        remaining[selected] = False

    assign(ndwi >= t.water, WATER)
    assign(ndvi >= t.dense_vegetation, DENSE_VEGETATION)
    assign(ndvi >= t.vegetation, SPARSE_VEGETATION)
    if ndbi is None:
        codes[remaining] = BARE_OR_BUILT_UP
    else:
        assign(ndbi >= t.built_up, BUILT_UP)
        codes[remaining] = BARE_SOIL
    return codes


def _is_nodata(value: float, nodata: float | None) -> bool:
    if nodata is None:
        return False
    if math.isnan(nodata):
        return math.isnan(value)
    return value == nodata


def _classify_stdlib(green, red, nir, swir, t, scale, offset, mask):
    size = green.size
    codes = new_sample_buffer("uint8", size, CLASS_NODATA)
    sources = [green, red, nir] + ([swir] if swir is not None else [])

    for index in range(size):
        if mask is not None and not mask[index]:
            continue

        raw = [float(band.values[index]) for band in sources]
        if any(_is_nodata(value, band.nodata) for value, band in zip(raw, sources)):
            continue
        scaled = [(value + offset) * scale for value in raw]
        if not all(math.isfinite(value) for value in scaled):
            continue

        g, r, n = scaled[0], scaled[1], scaled[2]
        s = scaled[3] if swir is not None else None
        if n + r == 0 or g + n == 0 or (s is not None and s + n == 0):
            continue

        ndvi = (n - r) / (n + r)
        ndwi = (g - n) / (g + n)
        ndbi = (s - n) / (s + n) if s is not None else None
        codes[index] = rule(ndvi, ndwi, ndbi, t)
    return codes


def _count(codes: Any, palette: tuple[int, ...]) -> dict[str, int]:
    if has_numpy():
        import numpy

        values = numpy.asarray(codes)
        return {CLASS_LABELS[code]: int((values == code).sum()) for code in palette}

    counts = {CLASS_LABELS[code]: 0 for code in palette}
    for value in codes:
        label = CLASS_LABELS.get(int(value))
        if label in counts:
            counts[label] += 1
    return counts


__all__ = [
    "BARE_OR_BUILT_UP",
    "BARE_SOIL",
    "BUILT_UP",
    "CODES_WITHOUT_SWIR",
    "CODES_WITH_SWIR",
    "CLASS_LABELS",
    "CLASS_NODATA",
    "DENSE_VEGETATION",
    "LandCoverResult",
    "SPARSE_VEGETATION",
    "Thresholds",
    "WATER",
    "classify_land_cover",
    "rule",
]
