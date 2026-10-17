"""SAR water and flood mapping by backscatter thresholding.

Smooth open water reflects the radar pulse away from the sensor, so it appears
as the darkest surface in a SAR image. Thresholding calibrated backscatter in
decibels is the long-established way to map it -- and, because radar sees
through cloud and at night, it is the standard first map in a flood response,
when optical imagery is usually unusable.

    water  where  sigma0_dB(polarisation) < threshold

The tool reports what it did as precisely as what it found: which
polarisation, which units the input was read as, which threshold and how it
was chosen, and whether speckle was filtered.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import (
    Artifact,
    RemoteSensingTool,
    StepLog,
    ToolExecutionError,
    ToolOutput,
    ToolRequest,
)
from app.tools.indices.index_tool import attach_areas, write_result_raster
from app.tools.indices.spec import numeric_parameter
from app.tools.raster.bands import normalise
from app.tools.raster.aoi import footprint_lonlat, open_for_analysis
from app.tools.raster.io import backend_report
from app.tools.raster.locate import class_locations
from app.tools.raster.render import write_preview
from app.tools.sar.flood import execute_flood
from app.tools.sar.backscatter import (
    CLASS_LABELS,
    DEFAULT_WATER_THRESHOLD_DB,
    calibrated_decibels,
    classify_water,
    decibel_band,
    otsu_threshold,
    resolve_polarisation,
    summarise_decibels,
)

THRESHOLD_METHODS = {"fixed", "otsu"}
SPECKLE_FILTERS = {"none", "boxcar"}
INPUT_UNITS = {"auto", "db", "linear"}
#: Speckle is filtered by default: single-pixel thresholds on unfiltered
#: radar produce salt-and-pepper water. 3x3 at 10 m smooths 30 m, well below
#: the size of any water body worth mapping. Set speckle_filter="none" to
#: threshold the raw pixels.
DEFAULT_SPECKLE_FILTER = "boxcar"
DEFAULT_FILTER_WINDOW = 3


def _choice(parameters: dict[str, Any], name: str, allowed: set[str], default: str) -> str:
    value = str(parameters.get(name) or default).strip().lower()
    if value not in allowed:
        raise ToolExecutionError(
            f"Unknown {name} '{parameters.get(name)}'. Use one of {sorted(allowed)}."
        )
    return value


def _window(parameters: dict[str, Any]) -> int:
    raw = parameters.get("filter_window")
    if raw is None:
        return DEFAULT_FILTER_WINDOW
    try:
        window = int(raw)
    except (TypeError, ValueError) as error:
        raise ToolExecutionError(f"filter_window must be an integer, got {raw!r}.") from error
    if window < 3 or window % 2 == 0 or window > 31:
        raise ToolExecutionError("filter_window must be an odd integer between 3 and 31.")
    return window


def calibration_options(parameters: dict[str, Any]) -> tuple[str, str, int]:
    """``(input_units, speckle_filter, window)`` from tool parameters, checked."""
    return (
        _choice(parameters, "input_units", INPUT_UNITS, "auto"),
        _choice(parameters, "speckle_filter", SPECKLE_FILTERS, DEFAULT_SPECKLE_FILTER),
        _window(parameters),
    )


def water_threshold(
    decibels: Any, valid: Any, polarisation: str, parameters: dict[str, Any]
) -> tuple[float, str, str]:
    """``(threshold_db, description, method)`` for mapping water in ``decibels``."""
    method = _choice(parameters, "threshold_method", THRESHOLD_METHODS, "fixed")
    if method == "otsu":
        threshold = otsu_threshold(decibels, valid)
        return threshold, f"Otsu threshold of {threshold:.2f} dB", method
    default = DEFAULT_WATER_THRESHOLD_DB.get(polarisation, -18.0)
    threshold = numeric_parameter(parameters, "threshold_db", default)
    return threshold, f"fixed threshold of {threshold:g} dB", method


class SARAnalysisTool(RemoteSensingTool):
    """Maps open water in a calibrated SAR backscatter image."""

    tool_id = "sar_analysis"
    result_type = "sar_water_map"

    def preflight(self, request: ToolRequest) -> None:
        parameters = request.parameters
        _choice(parameters, "threshold_method", THRESHOLD_METHODS, "fixed")
        _choice(parameters, "speckle_filter", SPECKLE_FILTERS, DEFAULT_SPECKLE_FILTER)
        _choice(parameters, "input_units", INPUT_UNITS, "auto")
        numeric_parameter(parameters, "threshold_db", 0.0)
        _window(parameters)

    def execute(self, request: ToolRequest) -> ToolOutput:
        self.preflight(request)
        if len(request.input_references) == 2:
            # A dry-season reference and a flood-period scene: flooding is
            # mapped as new water, so permanent water is not counted.
            return execute_flood(
                self.tool_id,
                request,
                calibration_options(request.parameters),
                lambda decibels, valid, polarisation: water_threshold(
                    decibels, valid, polarisation, request.parameters
                ),
            )
        path = self.require_single_input(request)
        parameters = request.parameters
        log = StepLog()
        with log.step("open", "read and clip the imagery"):
            dataset, aoi = open_for_analysis(path, parameters)

        band = resolve_polarisation(dataset, parameters.get("polarisation"))
        polarisation = normalise(band.name)

        requested_units, speckle_filter, window = calibration_options(parameters)
        with log.step("calibrate", f"{band.name} to dB, speckle filter {speckle_filter}"):
            decibels, valid, units = calibrated_decibels(
                band, dataset.width, dataset.height, requested_units, speckle_filter, window
            )

        threshold, threshold_description, method = water_threshold(
            decibels, valid, polarisation, parameters
        )

        with log.step("threshold", threshold_description):
            water_map, counts = classify_water(
                decibels, valid, threshold, dataset.width, dataset.height
            )
            locations = class_locations(water_map.values, {1: "water"}, dataset)

        valid_pixels = counts["water"] + counts["non_water"]
        total = dataset.width * dataset.height
        classes = {
            label: {
                "pixels": counts[label],
                "fraction": counts[label] / valid_pixels if valid_pixels else 0.0,
            }
            for label in ("water", "non_water")
        }
        statistics: dict[str, Any] = {
            **summarise_decibels(decibels, valid),
            "valid_pixels": valid_pixels,
            "nodata_pixels": total - valid_pixels,
            "total_pixels": total,
            "valid_fraction": valid_pixels / total if total else 0.0,
            "water_pixels": counts["water"],
            "water_fraction": classes["water"]["fraction"],
        }
        attach_areas(classes, statistics, dataset)

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            artifacts = [
                write_result_raster(
                    request=request,
                    dataset=dataset,
                    band=water_map,
                    source_path=path,
                    suffix="sar_water",
                    artifact_id="sar_water_raster",
                    description=(
                        "Single-band uint8 water map: 0 = nodata, 1 = water, "
                        f"2 = not water ({polarisation.upper()} below "
                        f"{threshold:.2f} dB is water)."
                    ),
                    dtype="uint8",
                    nodata=0,
                ),
                write_result_raster(
                    request=request,
                    dataset=dataset,
                    band=decibel_band(
                        decibels, dataset.width, dataset.height, f"{polarisation}_db"
                    ),
                    source_path=path,
                    suffix=f"{polarisation}_db",
                    artifact_id="sar_backscatter_db_raster",
                    description=(
                        f"Single-band float32 {polarisation.upper()} backscatter in dB"
                        + (f" after a {window}x{window} boxcar filter" if speckle_filter == "boxcar" else "")
                        + "; nodata is NaN."
                    ),
                ),
                write_preview(request, dataset, path),
            ]

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "method": "backscatter_threshold",
                "polarisation": polarisation.upper(),
                "input_units": units,
                "input_units_source": "detected" if requested_units == "auto" else "parameter",
                "threshold": threshold,
                "threshold_method": method,
                "threshold_description": threshold_description,
                "speckle_filter": (
                    f"{window}x{window} boxcar on linear power"
                    if speckle_filter == "boxcar"
                    else "none"
                ),
                "classes": classes,
                "class_locations": locations,
                "class_codes": {str(code): label for code, label in CLASS_LABELS.items()},
                "interpretation": (
                    "Smooth open water scatters the radar pulse away from the "
                    "sensor and is the darkest surface in the image. Wind-roughened "
                    "water can read as land, and radar shadow, tarmac or very dry "
                    "sand can read as water, so check edges against local knowledge."
                ),
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "source": dataset.describe(),
                "sensor": dataset.metadata.get("sensor"),
                "aoi": aoi,
                "footprint_lonlat": footprint_lonlat(dataset),
                "steps": log.steps,
                **backend_report(),
            },
        )


__all__ = ["SARAnalysisTool", "calibration_options", "water_threshold"]
