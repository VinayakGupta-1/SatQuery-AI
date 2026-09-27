"""Shared implementation for the normalised-difference index tools.

NDVI, NDWI and NDBI differ only in which bands fill the two roles of the
normalised difference and in how the resulting values are interpreted. Each
concrete tool therefore declares an :class:`IndexSpec` and inherits the
execution here.
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
from app.tools.indices.common import NODATA, classify_ranges
from app.tools.indices.spec import IndexSpec, compute_index
from app.tools.raster.aoi import footprint_lonlat, open_for_analysis
from app.tools.raster.io import backend_report, write_raster
from app.tools.raster.locate import range_locations
from app.tools.raster.model import RasterError
from app.tools.raster.render import write_preview


class NormalizedDifferenceIndexTool(RemoteSensingTool):
    """Computes ``(positive - negative) / (positive + negative)`` on a raster."""

    result_type = "raster_index"

    #: The index this tool computes.
    spec: IndexSpec

    def execute(self, request: ToolRequest) -> ToolOutput:
        path = self.require_single_input(request)
        parameters = request.parameters
        log = StepLog()

        with log.step("open", "read and clip the imagery"):
            dataset, aoi = open_for_analysis(path, parameters)
        sensor = parameters.get("sensor") or dataset.metadata.get("sensor")

        with log.step("compute", f"{self.spec.name} per pixel"):
            computation = compute_index(dataset, self.spec, parameters, sensor)
        statistics = computation.statistics

        with log.step("summarise", "classes, areas and where they lie"):
            classes = classify_ranges(computation.band, self.spec.interpretation_ranges)
            attach_areas(classes, statistics, dataset)
            locations = range_locations(computation.band, self.spec.interpretation_ranges, dataset)

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            with log.step("write", "index raster and scene picture"):
                artifacts.append(
                    write_result_raster(
                        request=request,
                        dataset=dataset,
                        band=computation.band,
                        source_path=path,
                        suffix=self.spec.name.lower(),
                        artifact_id=f"{self.tool_id}_raster",
                        description=(
                            f"Single-band float32 {self.spec.name} raster on the source "
                            "grid; pixels that could not be computed are nodata (NaN)."
                        ),
                    )
                )
                artifacts.append(write_preview(request, dataset, path))

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "index": self.spec.name,
                "formula": computation.formula,
                "positive_band": computation.positive.name,
                "negative_band": computation.negative.name,
                "interpretation": self.spec.interpretation_note,
                "classes": classes,
                "class_locations": locations,
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "source": dataset.describe(),
                "sensor": sensor,
                "scale": float(parameters.get("scale") or 1.0),
                "offset": float(parameters.get("offset") or 0.0),
                "mask": computation.mask_report,
                "aoi": aoi,
                "footprint_lonlat": footprint_lonlat(dataset),
                "steps": log.steps,
                **backend_report(),
            },
        )


# ============================================================
# SHARED HELPERS
# ============================================================
def attach_areas(
    classes: dict[str, dict[str, Any]],
    statistics: dict[str, Any],
    dataset: Any,
) -> None:
    """Convert pixel counts to ground area when the raster is georeferenced."""
    pixel_area = dataset.georeference.pixel_area()
    if pixel_area is None:
        return
    statistics["pixel_area_square_units"] = pixel_area
    statistics["valid_area_square_units"] = statistics["valid_pixels"] * pixel_area
    for summary in classes.values():
        summary["area_square_units"] = summary["pixels"] * pixel_area


def write_result_raster(
    request: ToolRequest,
    dataset: Any,
    band: Any,
    source_path: str,
    suffix: str,
    artifact_id: str,
    description: str,
    dtype: str = "float32",
    nodata: float | None = NODATA,
) -> Artifact:
    """Write one result band next to the task's other outputs."""
    stem = os.path.splitext(os.path.basename(source_path))[0]
    output_path = os.path.join(
        request.resolved_output_directory(), f"{stem}_{suffix}.tif"
    )
    try:
        write_raster(
            output_path,
            [band],
            dataset.georeference,
            dtype=dtype,
            nodata=nodata,
            metadata={"sensor": dataset.metadata.get("sensor")},
        )
    except RasterError as error:
        raise ToolExecutionError(
            f"The result was computed but could not be written to {output_path}: {error}"
        ) from error

    return Artifact(
        artifact_id=artifact_id,
        kind="raster",
        path=output_path,
        format="GTiff",
        description=description,
    )
