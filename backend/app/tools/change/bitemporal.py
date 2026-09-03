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
from app.tools.raster.io import backend_report, open_raster, write_raster
from app.tools.raster.model import RasterError

DEFAULT_INDEX = "ndvi"
DEFAULT_THRESHOLD = 0.2
DEFAULT_SIGMA_MULTIPLIER = 2.0

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

        spec = get_index_spec(parameters.get("index") or DEFAULT_INDEX)
        if spec is None:
            raise ToolExecutionError(
                f"Unknown index '{parameters.get('index')}'. Available indices: "
                f"{available_indices()}."
            )

        try:
            first = open_raster(earlier_path)
            second = open_raster(later_path)
        except RasterError as error:
            raise ToolExecutionError(str(error)) from error

        require_aligned(first, second)
        earlier, later, ordering = order_by_acquisition(first, second)

        sensor = parameters.get("sensor") or earlier.metadata.get("sensor")
        before = compute_index(earlier, spec, parameters, sensor)
        after = compute_index(later, spec, parameters, sensor)

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

        classes = self._summarise_classes(counts, statistics, earlier)
        statistics["changed_pixels"] = counts["increase"] + counts["decrease"]
        statistics["changed_fraction"] = (
            statistics["changed_pixels"] / statistics["valid_pixels"]
            if statistics["valid_pixels"]
            else 0.0
        )

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            artifacts = self._write_outputs(
                request, earlier, change, classification, spec.name
            )

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
                **ordering,
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "earlier": earlier.describe(),
                "later": later.describe(),
                "sensor": sensor,
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
