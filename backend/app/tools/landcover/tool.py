"""Land-cover classification as a registered tool.

The arithmetic lives in :mod:`app.tools.landcover.classifier`. This module
resolves bands and parameters, runs the classifier, and shapes the result --
and it exposes :func:`classify_dataset` so region detection can build on
exactly the same classification rather than a second copy of the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
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
from app.tools.indices.spec import mask_from_parameters, numeric_parameter
from app.tools.landcover.classifier import (
    CLASS_LABELS,
    LandCoverResult,
    Thresholds,
    classify_land_cover,
)
from app.tools.raster.aoi import footprint_lonlat, open_for_analysis
from app.tools.raster.bands import resolve_band
from app.tools.raster.io import backend_report
from app.tools.raster.locate import class_locations
from app.tools.raster.model import BandArray, RasterDataset, RasterError
from app.tools.raster.render import write_preview

#: Parameter name -> the logical band it names by default.
BAND_ROLES = {
    "green_band": "green",
    "red_band": "red",
    "nir_band": "nir",
}

INTERPRETATION = (
    "Each pixel was assigned by transparent spectral-index rules rather than a "
    "trained model, so every label can be traced to its NDWI, NDVI and NDBI "
    "values. NDBI cannot fully separate bare soil from built-up land; treat "
    "those two classes as indicative where they border each other."
)

INTERPRETATION_WITHOUT_SWIR = (
    "Each pixel was assigned by transparent spectral-index rules rather than a "
    "trained model. The scene has no SWIR band, so bare ground and built-up "
    "land cannot be told apart and are reported together."
)


def thresholds_from(parameters: dict[str, Any]) -> Thresholds:
    """Read and validate the rule thresholds from tool parameters."""
    defaults = Thresholds()
    return Thresholds(
        water=numeric_parameter(parameters, "water_threshold", defaults.water),
        vegetation=numeric_parameter(
            parameters, "vegetation_threshold", defaults.vegetation
        ),
        dense_vegetation=numeric_parameter(
            parameters, "dense_vegetation_threshold", defaults.dense_vegetation
        ),
        built_up=numeric_parameter(parameters, "built_up_threshold", defaults.built_up),
    ).validate()


@dataclass
class DatasetClassification:
    """A land-cover classification together with where it came from."""

    result: LandCoverResult
    thresholds: Thresholds
    bands: dict[str, str]
    mask_report: dict[str, Any] | None
    sensor: str | None


def _resolve_bands(
    dataset: RasterDataset, parameters: dict[str, Any], sensor: str | None
) -> tuple[dict[str, BandArray], BandArray | None]:
    try:
        roles = {
            role: resolve_band(dataset, parameters.get(name) or role, sensor)
            for name, role in BAND_ROLES.items()
        }
    except RasterError as error:
        raise ToolExecutionError(str(error)) from error

    # SWIR is optional: without it the classifier still runs, with bare and
    # built-up land merged. A band the caller named explicitly must exist.
    swir: BandArray | None = None
    if parameters.get("swir_band"):
        try:
            swir = resolve_band(dataset, parameters["swir_band"], sensor)
        except RasterError as error:
            raise ToolExecutionError(str(error)) from error
    else:
        try:
            swir = resolve_band(dataset, "swir1", sensor)
        except RasterError:
            swir = None

    names = [band.name for band in roles.values()] + ([swir.name] if swir else [])
    if len(set(names)) != len(names):
        raise ToolExecutionError(
            f"Land-cover classification needs distinct green, red, NIR (and SWIR) "
            f"bands, but they resolved to {names}."
        )
    return roles, swir


def classify_dataset(
    dataset: RasterDataset, parameters: dict[str, Any]
) -> DatasetClassification:
    """Classify an opened dataset using the tool's parameters."""
    sensor = parameters.get("sensor") or dataset.metadata.get("sensor")
    thresholds = thresholds_from(parameters)
    roles, swir = _resolve_bands(dataset, parameters, sensor)
    mask, mask_report = mask_from_parameters(dataset, parameters, sensor)

    result = classify_land_cover(
        roles["green"],
        roles["red"],
        roles["nir"],
        swir,
        thresholds,
        scale=numeric_parameter(parameters, "scale", 1.0),
        offset=numeric_parameter(parameters, "offset", 0.0),
        mask=mask,
    )
    bands = {role: band.name for role, band in roles.items()}
    if swir is not None:
        bands["swir"] = swir.name
    return DatasetClassification(result, thresholds, bands, mask_report, sensor)


class LandCoverClassificationTool(RemoteSensingTool):
    """Classifies an optical scene into water, vegetation, built-up and bare land."""

    tool_id = "land_cover_classification"
    result_type = "land_cover"

    def preflight(self, request: ToolRequest) -> None:
        thresholds_from(request.parameters)

    def execute(self, request: ToolRequest) -> ToolOutput:
        path = self.require_single_input(request)
        log = StepLog()
        with log.step("open", "read and clip the imagery"):
            dataset, aoi = open_for_analysis(path, request.parameters)

        with log.step("classify", "NDWI, NDVI and NDBI rules per pixel"):
            classification = classify_dataset(dataset, request.parameters)
        result = classification.result

        valid = result.valid_pixels
        classes = {
            label: {
                "pixels": result.counts[label],
                "fraction": (result.counts[label] / valid) if valid else 0.0,
            }
            for label in result.labels
        }
        statistics: dict[str, Any] = {
            "valid_pixels": valid,
            "nodata_pixels": result.total_pixels - valid,
            "total_pixels": result.total_pixels,
            "valid_fraction": valid / result.total_pixels if result.total_pixels else 0.0,
        }
        if classification.mask_report:
            statistics["masked_pixels"] = classification.mask_report["masked_pixels"]
            statistics["masked_fraction"] = classification.mask_report["masked_fraction"]
        attach_areas(classes, statistics, dataset)
        code_labels = {code: label for code, label in CLASS_LABELS.items() if label in result.labels}
        with log.step("locate", "where each class lies"):
            locations = class_locations(result.band.values, code_labels, dataset)

        artifacts: list[Artifact] = []
        if request.parameters.get("write_raster", True):
            legend = ", ".join(
                f"{code} = {CLASS_LABELS[code].replace('_', ' ')}"
                for code in sorted(CLASS_LABELS)
                if CLASS_LABELS[code] in result.labels
            )
            artifacts.append(
                write_result_raster(
                    request=request,
                    dataset=dataset,
                    band=result.band,
                    source_path=path,
                    suffix="land_cover",
                    artifact_id="land_cover_raster",
                    description=f"Single-band uint8 land-cover map: 0 = nodata, {legend}.",
                    dtype="uint8",
                    nodata=0,
                )
            )
            artifacts.append(write_preview(request, dataset, path))

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "method": "rule_based_spectral_indices",
                "classes": classes,
                "class_codes": {
                    str(code): label
                    for code, label in CLASS_LABELS.items()
                    if label in result.labels
                },
                "class_locations": locations,
                "rules": classification.thresholds.describe(result.has_swir),
                "bands": classification.bands,
                "swir_available": result.has_swir,
                "interpretation": (
                    INTERPRETATION if result.has_swir else INTERPRETATION_WITHOUT_SWIR
                ),
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "source": dataset.describe(),
                "sensor": classification.sensor,
                "mask": classification.mask_report,
                "aoi": aoi,
                "footprint_lonlat": footprint_lonlat(dataset),
                "steps": log.steps,
                **backend_report(),
            },
        )


__all__ = [
    "DatasetClassification",
    "LandCoverClassificationTool",
    "classify_dataset",
    "thresholds_from",
]
