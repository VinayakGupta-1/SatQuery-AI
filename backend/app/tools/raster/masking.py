"""Excluding cloud, shadow and defective pixels before analysis.

Clouds are bright in both red and near-infrared, so an NDVI computed over them
is not merely noisy -- it is a confident number describing the top of a cloud.
Averaging that across a scene silently corrupts the statistics, and nothing in
the result would reveal it. Masking is therefore part of computing an index
correctly, not an optional refinement.

Sentinel-2 Level-2A products ship a Scene Classification Layer (SCL) for
exactly this purpose. Landsat Collection-2 ships QA_PIXEL. Either can be named
as the mask band; the classes treated as unusable are configurable, because the
right answer depends on the question (snow is worthless for vegetation
analysis and essential for snow-cover analysis).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.tools.raster.backends import has_numpy
from app.tools.raster.bands import resolve_band
from app.tools.raster.model import RasterDataset

# Sentinel-2 Level-2A Scene Classification Layer codes.
SCL_CLASSES: dict[int, str] = {
    0: "no_data",
    1: "saturated_or_defective",
    2: "dark_area_pixels",
    3: "cloud_shadows",
    4: "vegetation",
    5: "not_vegetated",
    6: "water",
    7: "unclassified",
    8: "cloud_medium_probability",
    9: "cloud_high_probability",
    10: "thin_cirrus",
    11: "snow_or_ice",
}

#: Classes excluded unless the caller says otherwise: missing data, defective
#: detectors, cloud shadow, both cloud probabilities, and cirrus.
#:
#: Two classes are deliberately *not* excluded by default. Dark-area pixels (2)
#: include genuine dark ground such as water and burn scars, and snow (11) is
#: real surface the user may well be asking about. Both can be added through
#: ``mask_invalid_values`` when the analysis calls for it.
DEFAULT_SCL_INVALID: tuple[int, ...] = (0, 1, 3, 8, 9, 10)


def parse_mask_values(raw: Any) -> tuple[int, ...] | None:
    """Read the invalid-class list from a parameter value.

    Accepts a list of integers or a comma-separated string, because the same
    value arrives from a JSON API body and from a registry-typed string.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        parts: Iterable[str] = (part for part in raw.replace(";", ",").split(",") if part.strip())
        try:
            return tuple(int(part.strip()) for part in parts)
        except ValueError as error:
            raise ValueError(
                f"mask_invalid_values must be a comma-separated list of integers, "
                f"got {raw!r}."
            ) from error
    if isinstance(raw, (list, tuple)):
        try:
            return tuple(int(value) for value in raw)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"mask_invalid_values must contain integers, got {raw!r}."
            ) from error
    raise ValueError(f"mask_invalid_values must be a list or string, got {raw!r}.")


def build_validity_mask(
    dataset: RasterDataset,
    mask_band: str,
    invalid_values: Sequence[int] | None = None,
    sensor: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Return a per-pixel validity mask and a description of what it excluded.

    The mask is ``True`` where a pixel may be used. The report names the
    excluded classes by their SCL meaning so the exclusion is auditable rather
    than a bare count.
    """
    band = resolve_band(dataset, mask_band, sensor or dataset.metadata.get("sensor"))
    invalid = tuple(
        DEFAULT_SCL_INVALID if invalid_values is None else invalid_values
    )
    invalid_set = set(invalid)

    if has_numpy():
        import numpy

        codes = numpy.asarray(band.values)
        mask = ~numpy.isin(codes, list(invalid_set))
        excluded = int((~mask).sum())
        present = {int(code): int((codes == code).sum()) for code in numpy.unique(codes)}
    else:
        mask = [int(value) not in invalid_set for value in band.values]
        excluded = sum(1 for allowed in mask if not allowed)
        present = {}
        for value in band.values:
            code = int(value)
            present[code] = present.get(code, 0) + 1

    report = {
        "mask_band": band.name,
        "masked_pixels": excluded,
        "masked_fraction": excluded / band.size if band.size else 0.0,
        "excluded_classes": {
            code: SCL_CLASSES.get(code, "unknown") for code in sorted(invalid_set)
        },
        "class_histogram": {
            SCL_CLASSES.get(code, f"class_{code}"): count
            for code, count in sorted(present.items())
        },
    }
    return mask, report
