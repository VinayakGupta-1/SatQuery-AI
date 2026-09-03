"""Declarative description of a normalised-difference index.

An index is fully described by which bands fill the two roles and how the
resulting values should be read. Holding that as data rather than as behaviour
means two very different tools can compute the same index: the index tools
compute one, and bi-temporal change detection computes the same one twice and
differences the results, without either duplicating band resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.tools.base import ToolExecutionError
from app.tools.indices.common import normalized_difference
from app.tools.raster.bands import resolve_band
from app.tools.raster.masking import build_validity_mask, parse_mask_values
from app.tools.raster.model import BandArray, RasterDataset, RasterError


@dataclass(frozen=True)
class IndexSpec:
    """Everything that distinguishes one normalised-difference index."""

    name: str
    #: Registry parameter names carrying each band role.
    positive_parameter: str
    negative_parameter: str
    #: Logical band names used when the caller does not name a band.
    default_positive_band: str
    default_negative_band: str
    #: ``(label, lower, upper)`` ranges used to summarise a single-date result.
    interpretation_ranges: list[tuple[str, float, float]] = field(default_factory=list)
    interpretation_note: str = ""


@dataclass
class IndexComputation:
    """The outcome of computing one index over one dataset."""

    band: BandArray
    statistics: dict[str, Any]
    positive: BandArray
    negative: BandArray
    #: Describes what a cloud/QA mask excluded, when one was applied.
    mask_report: dict[str, Any] | None = None

    @property
    def formula(self) -> str:
        return f"({self.positive.name} - {self.negative.name}) / ({self.positive.name} + {self.negative.name})"


def numeric_parameter(parameters: dict[str, Any], name: str, default: float) -> float:
    """Read a numeric parameter, failing clearly rather than coercing badly."""
    if name not in parameters or parameters[name] is None:
        return default
    try:
        return float(parameters[name])
    except (TypeError, ValueError) as error:
        raise ToolExecutionError(
            f"Parameter '{name}' must be numeric, got {parameters[name]!r}."
        ) from error


def compute_index(
    dataset: RasterDataset,
    spec: IndexSpec,
    parameters: dict[str, Any] | None = None,
    sensor: str | None = None,
) -> IndexComputation:
    """Resolve the two bands ``spec`` needs and compute the index."""
    parameters = parameters or {}
    sensor = sensor or dataset.metadata.get("sensor")

    positive_id = parameters.get(spec.positive_parameter) or spec.default_positive_band
    negative_id = parameters.get(spec.negative_parameter) or spec.default_negative_band

    try:
        positive = resolve_band(dataset, positive_id, sensor)
        negative = resolve_band(dataset, negative_id, sensor)
    except RasterError as error:
        raise ToolExecutionError(str(error)) from error

    if positive.name == negative.name:
        raise ToolExecutionError(
            f"{spec.name} needs two distinct bands but '{positive_id}' and "
            f"'{negative_id}' both resolved to band '{positive.name}'."
        )

    mask, mask_report = _build_mask(dataset, parameters, sensor)

    band, statistics = normalized_difference(
        positive,
        negative,
        spec.name,
        scale=numeric_parameter(parameters, "scale", 1.0),
        offset=numeric_parameter(parameters, "offset", 0.0),
        mask=mask,
    )
    if mask_report:
        statistics.update(
            {
                "masked_pixels": mask_report["masked_pixels"],
                "masked_fraction": mask_report["masked_fraction"],
            }
        )

    return IndexComputation(
        band=band,
        statistics=statistics,
        positive=positive,
        negative=negative,
        mask_report=mask_report,
    )


def _build_mask(
    dataset: RasterDataset,
    parameters: dict[str, Any],
    sensor: str | None,
) -> tuple[Any, dict[str, Any] | None]:
    """Build a cloud/QA validity mask when the caller named a mask band."""
    mask_band = parameters.get("mask_band")
    if not mask_band:
        return None, None

    try:
        invalid = parse_mask_values(parameters.get("mask_invalid_values"))
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error

    try:
        return build_validity_mask(dataset, str(mask_band), invalid, sensor)
    except RasterError as error:
        raise ToolExecutionError(
            f"The mask band could not be resolved: {error}"
        ) from error
