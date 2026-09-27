"""Bi-temporal change detection by spectral index differencing.

The method is deliberately deterministic and long-established: compute the same
normalised index on two dates over an identical grid, difference the results,
and threshold the magnitude. For NDVI this detects vegetation gain and loss --
clearing, regrowth, crop cycles, flood damage; for NDWI it detects water extent
change; for NDBI, urban expansion.

    change = index(later) - index(earlier)

Three properties keep the result trustworthy:

*Alignment is proven, not assumed.* The pair must occupy one pixel grid, or the
run fails with an instruction to co-register.

*Order comes from acquisition dates* where the files carry them, so the sign of
the change does not depend on which file the user uploaded first.

*A pixel is classified only where both dates are valid.* Ground observed once
produces nodata, never a change value.
"""

from __future__ import annotations

import os
from typing import Any

from app.tools.base import (
    Artifact,
    RemoteSensingTool,
    StepLog,
    ToolExecutionError,
    ToolOutput,
    ToolRequest,
)
from app.tools.change.alignment import order_by_acquisition, require_aligned
from app.tools.change.arithmetic import (
    CLASS_LABELS,
    classify_change,
    difference,
    resolve_threshold,
)
from app.tools.indices.catalog import available_indices, get_index_spec
from app.tools.indices.spec import compute_index, numeric_parameter
from app.tools.raster.aoi import (
    area_from_parameters,
    clip,
    describe_clip,
    footprint_lonlat,
    window_for,
)
from app.tools.raster.io import backend_report, open_raster, write_raster
from app.tools.raster.locate import class_locations
from app.tools.raster.model import RasterError
from app.tools.raster.render import write_preview
from app.tools.sar.backscatter import (
    calibrated_decibels,
    decibel_band,
    is_sar,
    resolve_polarisation,
)

DEFAULT_INDEX = "ndvi"
DEFAULT_THRESHOLD = 0.2
DEFAULT_SIGMA_MULTIPLIER = 2.0

#: A doubling or halving of returned power: the conventional SAR change cut.
DEFAULT_SAR_THRESHOLD_DB = 3.0
DEFAULT_SAR_SPECKLE_FILTER = "boxcar"
#: Larger than for single-date water mapping: a difference of two images
#: carries the speckle of both.
DEFAULT_SAR_FILTER_WINDOW = 5

#: The change classes worth locating; "stable" is everywhere else.
CHANGE_LOCATED = {1: "decrease", 3: "increase"}


def _clip_pair(earlier: Any, later: Any, parameters: dict[str, Any]):
    """Clip both dates to the requested area with one window.

    The pair has already been proven to share a grid, so the window computed
    on one covers exactly the same ground in the other.
    """
    area = area_from_parameters(parameters)
    if area is None:
        return earlier, later, None
    window = window_for(earlier, area)
    clipped_earlier, clipped_later = clip(earlier, window), clip(later, window)
    return clipped_earlier, clipped_later, describe_clip(earlier, clipped_earlier, area, window)

#: What a rise in each index means on the ground, used to describe the result
#: in the caller's terms rather than as a bare "increase".
INCREASE_MEANING = {
    "NDVI": "vegetation gain",
    "NDWI": "water extent gain",
    "NDBI": "built-up expansion",
}
DECREASE_MEANING = {
    "NDVI": "vegetation loss",
    "NDWI": "water extent loss",
    "NDBI": "built-up reduction",
}


class BiTemporalChangeDetectionTool(RemoteSensingTool):
    """Detects change between two co-registered, differently dated rasters."""

    tool_id = "change_detection"
    result_type = "change_map"

    def execute(self, request: ToolRequest) -> ToolOutput:
        earlier_path, later_path = self._require_pair(request)
        parameters = request.parameters
        log = StepLog()

        with log.step("open", "read both dates, check alignment, clip"):
            try:
                first = open_raster(earlier_path)
                second = open_raster(later_path)
            except RasterError as error:
                raise ToolExecutionError(str(error)) from error

            require_aligned(first, second)
            earlier, later, ordering = order_by_acquisition(first, second)
            earlier, later, aoi = _clip_pair(earlier, later, parameters)

        # A radar pair has no spectral bands to compute an index from; it is
        # compared by backscatter instead.
        if is_sar(earlier) and is_sar(later):
            return self._execute_sar(request, earlier, later, ordering, aoi, log)

        spec = get_index_spec(parameters.get("index") or DEFAULT_INDEX)
        if spec is None:
            raise ToolExecutionError(
                f"Unknown index '{parameters.get('index')}'. Available indices: "
                f"{available_indices()}."
            )

        sensor = parameters.get("sensor") or earlier.metadata.get("sensor")
        with log.step("compute", f"{spec.name} on both dates"):
            before = compute_index(earlier, spec, parameters, sensor)
            after = compute_index(later, spec, parameters, sensor)

        with log.step("difference", f"d{spec.name} = later - earlier"):
            change, statistics = difference(
                after.band, before.band, name=f"d{spec.name}"
            )

        threshold, threshold_description = resolve_threshold(
            statistics,
            method=parameters.get("threshold_method") or "fixed",
            fixed=numeric_parameter(parameters, "threshold", DEFAULT_THRESHOLD),
            sigma_multiplier=numeric_parameter(
                parameters, "sigma_multiplier", DEFAULT_SIGMA_MULTIPLIER
            ),
        )
        classification, counts = classify_change(change, threshold)
        locations = class_locations(classification.values, CHANGE_LOCATED, earlier)

        classes = self._summarise_classes(counts, statistics, earlier)
        statistics["changed_pixels"] = counts["increase"] + counts["decrease"]
        statistics["changed_fraction"] = (
            statistics["changed_pixels"] / statistics["valid_pixels"]
            if statistics["valid_pixels"]
            else 0.0
        )

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            with log.step("write", "change rasters and scene picture"):
                artifacts = self._write_outputs(
                    request, earlier, change, classification, spec.name
                )
                artifacts.append(write_preview(request, later, later.path or "later"))

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "index": spec.name,
                "method": "index_difference",
                "formula": f"d{spec.name} = {spec.name}(later) - {spec.name}(earlier)",
                "index_formula": before.formula,
                "threshold": threshold,
                "threshold_description": threshold_description,
                "threshold_method": parameters.get("threshold_method") or "fixed",
                "increase_means": INCREASE_MEANING.get(spec.name, "an increase"),
                "decrease_means": DECREASE_MEANING.get(spec.name, "a decrease"),
                "classes": classes,
                "class_locations": locations,
                **ordering,
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "earlier": earlier.describe(),
                "later": later.describe(),
                "sensor": sensor,
                "aoi": aoi,
                "footprint_lonlat": footprint_lonlat(earlier),
                "steps": log.steps,
                **backend_report(),
            },
        )

    def _execute_sar(
        self,
        request: ToolRequest,
        earlier: Any,
        later: Any,
        ordering: dict[str, Any],
        aoi: dict[str, Any] | None = None,
        log: StepLog | None = None,
    ) -> ToolOutput:
        """Compare two radar scenes by the log-ratio of their backscatter.

        The difference of two dB images is the log of the ratio of their
        power, which is the standard SAR change measure: multiplicative
        speckle becomes additive, and a +/-3 dB change is a doubling or halving
        of the returned energy. Speckle is filtered first by default, because
        the difference of two unfiltered speckled images is mostly speckle.
        """
        parameters = request.parameters
        requested = parameters.get("polarisation")
        before_band = resolve_polarisation(earlier, requested)
        after_band = resolve_polarisation(later, requested or before_band.name)
        polarisation = before_band.name.upper()

        units = str(parameters.get("input_units") or "auto").strip().lower()
        speckle_filter = str(parameters.get("speckle_filter") or DEFAULT_SAR_SPECKLE_FILTER).strip().lower()
        window = int(numeric_parameter(parameters, "filter_window", DEFAULT_SAR_FILTER_WINDOW))

        log = log or StepLog()
        with log.step("calibrate", f"{polarisation} to dB on both dates, speckle filter {speckle_filter}"):
            before_db, _, before_units = calibrated_decibels(
                before_band, earlier.width, earlier.height, units, speckle_filter, window
            )
            after_db, _, _ = calibrated_decibels(
                after_band, later.width, later.height, units, speckle_filter, window
            )
        before = decibel_band(before_db, earlier.width, earlier.height, f"{polarisation}_dB")
        after = decibel_band(after_db, later.width, later.height, f"{polarisation}_dB")

        change, statistics = difference(after, before, name=f"d{polarisation}")
        threshold, threshold_description = resolve_threshold(
            statistics,
            method=parameters.get("threshold_method") or "fixed",
            fixed=numeric_parameter(parameters, "threshold", DEFAULT_SAR_THRESHOLD_DB),
            sigma_multiplier=numeric_parameter(
                parameters, "sigma_multiplier", DEFAULT_SIGMA_MULTIPLIER
            ),
        )
        classification, counts = classify_change(change, threshold)
        locations = class_locations(classification.values, CHANGE_LOCATED, earlier)

        classes = self._summarise_classes(counts, statistics, earlier)
        statistics["changed_pixels"] = counts["increase"] + counts["decrease"]
        statistics["changed_fraction"] = (
            statistics["changed_pixels"] / statistics["valid_pixels"]
            if statistics["valid_pixels"]
            else 0.0
        )

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            with log.step("write", "change rasters and scene picture"):
                artifacts = self._write_outputs(
                    request, earlier, change, classification, f"{polarisation}_dB"
                )
                artifacts.append(write_preview(request, later, later.path or "later"))

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "index": f"{polarisation} backscatter",
                "method": "sar_log_ratio",
                "formula": f"d{polarisation} = {polarisation}_dB(later) - {polarisation}_dB(earlier)",
                "index_formula": f"{polarisation}_dB = 10 log10(sigma0)",
                "threshold": threshold,
                "threshold_units": "dB",
                "threshold_description": f"{threshold_description} dB",
                "threshold_method": parameters.get("threshold_method") or "fixed",
                "input_units": before_units,
                "speckle_filter": (
                    f"{window}x{window} boxcar on linear power"
                    if speckle_filter == "boxcar"
                    else "none"
                ),
                # Neutral about cause: a rise can be receding water, new
                # structures or crop growth; a fall is typical of new water.
                "increase_means": "backscatter gain",
                "decrease_means": "backscatter loss, typical of new open water",
                "classes": classes,
                "class_locations": locations,
                **ordering,
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "earlier": earlier.describe(),
                "later": later.describe(),
                "sensor": earlier.metadata.get("sensor"),
                "aoi": aoi,
                "footprint_lonlat": footprint_lonlat(earlier),
                "steps": log.steps,
                **backend_report(),
            },
        )

    # -- helpers -----------------------------------------------------
    def _require_pair(self, request: ToolRequest) -> tuple[str, str]:
        references = request.input_references
        if len(references) != 2:
            raise ToolExecutionError(
                f"Bi-temporal change detection requires exactly two rasters, but "
                f"{len(references)} were supplied."
            )
        return references[0], references[1]

    @staticmethod
    def _summarise_classes(
        counts: dict[str, int],
        statistics: dict[str, Any],
        dataset: Any,
    ) -> dict[str, dict[str, Any]]:
        valid = statistics["valid_pixels"]
        pixel_area = dataset.georeference.pixel_area()
        if pixel_area is not None:
            statistics["pixel_area_square_units"] = pixel_area
            statistics["valid_area_square_units"] = valid * pixel_area

        summary: dict[str, dict[str, Any]] = {}
        for label in CLASS_LABELS.values():
            pixels = counts[label]
            entry: dict[str, Any] = {
                "pixels": pixels,
                "fraction": (pixels / valid) if valid else 0.0,
            }
            if pixel_area is not None:
                entry["area_square_units"] = pixels * pixel_area
            summary[label] = entry
        return summary

    @staticmethod
    def _write_outputs(
        request: ToolRequest,
        dataset: Any,
        change: Any,
        classification: Any,
        index_name: str,
    ) -> list[Artifact]:
        directory = request.resolved_output_directory()
        stem = os.path.splitext(os.path.basename(dataset.path or "change"))[0]
        georeference = dataset.georeference
        metadata = {"sensor": dataset.metadata.get("sensor")}

        difference_path = os.path.join(
            directory, f"{stem}_d{index_name.lower()}.tif"
        )
        class_path = os.path.join(directory, f"{stem}_change_class.tif")

        try:
            write_raster(
                difference_path, [change], georeference,
                dtype="float32", nodata=change.nodata, metadata=metadata,
            )
            write_raster(
                class_path, [classification], georeference,
                dtype="uint8", nodata=0, metadata=metadata,
            )
        except RasterError as error:
            raise ToolExecutionError(
                f"Change was computed but could not be written: {error}"
            ) from error

        return [
            Artifact(
                artifact_id="change_difference_raster",
                kind="raster",
                path=difference_path,
                format="GTiff",
                description=(
                    f"Single-band float32 raster of {index_name}(later) minus "
                    f"{index_name}(earlier). Pixels not valid on both dates are "
                    "nodata (NaN)."
                ),
            ),
            Artifact(
                artifact_id="change_class_raster",
                kind="raster",
                path=class_path,
                format="GTiff",
                description=(
                    "Single-band uint8 change classification: "
                    "0 = nodata, 1 = decrease, 2 = stable, 3 = increase."
                ),
            ),
        ]
