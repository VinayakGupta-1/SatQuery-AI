"""Optical + SAR water fusion.

Floods come with cloud. An optical image sees water clearly where the sky is
clear and not at all under cloud; radar sees through cloud but confuses smooth
tarmac, radar shadow and dry sand with water. Fused, each sensor covers the
other's blind spot -- and where both can see, their agreement is itself a
measure of how far the water map can be trusted.

    optical water  NDWI >= threshold, on pixels the cloud mask leaves usable
    radar water    sigma0_dB < threshold, after speckle filtering
    fused water    the union, labelled by which sensor saw it

Every pixel is labelled with what each sensor said, so nothing about the
fusion is hidden: water both saw, water only radar saw (possibly flooded
vegetation, or a radar false alarm), water only optical saw (possibly
wind-roughened water), and water radar saw where the optical image was masked
by cloud. Cohen's kappa between the two water maps, over pixels both sensors
observed, reports how well they agree beyond chance.

The pair must share a pixel grid and be acquired within ``max_days_apart``
days: fusing images of different days would describe two different floods.
"""

from __future__ import annotations

import math
from typing import Any

from app.tools.base import (
    Artifact,
    RemoteSensingTool,
    StepLog,
    ToolExecutionError,
    ToolOutput,
    ToolRequest,
)
from app.tools.change.alignment import require_aligned
from app.tools.indices.index_tool import attach_areas, write_result_raster
from app.tools.indices.ndwi import NDWI_SPEC
from app.tools.indices.spec import compute_index, numeric_parameter
from app.tools.raster.aoi import (
    area_from_parameters,
    clip,
    describe_clip,
    footprint_lonlat,
    window_for,
)
from app.tools.raster.backends import has_numpy
from app.tools.raster.bands import normalise
from app.tools.raster.inspection import find_acquisition_date
from app.tools.raster.io import backend_report, open_raster
from app.tools.raster.locate import class_locations
from app.tools.raster.model import BandArray, RasterDataset, RasterError, new_sample_buffer
from app.tools.raster.render import write_preview
from app.tools.sar.backscatter import calibrated_decibels, is_sar, resolve_polarisation
from app.tools.sar.tool import SARAnalysisTool, calibration_options, water_threshold

CLASS_NODATA = 0
WATER_BOTH = 1
WATER_RADAR_ONLY = 2
WATER_OPTICAL_ONLY = 3
WATER_UNDER_CLOUD = 4
LAND = 5

CLASS_LABELS = {
    WATER_BOTH: "water_both",
    WATER_RADAR_ONLY: "water_radar_only",
    WATER_OPTICAL_ONLY: "water_optical_only",
    WATER_UNDER_CLOUD: "water_under_cloud",
    LAND: "land",
}
WATER_LABELS = ("water_both", "water_radar_only", "water_optical_only", "water_under_cloud")

DEFAULT_MAX_DAYS = 12
DEFAULT_OPTICAL_WATER_THRESHOLD = 0.0
#: Quality bands that mark cloud, used automatically when the optical image
#: carries one: fusion exists to see under cloud, so it has to know where
#: cloud is.
CLOUD_MASK_BANDS = ("scl", "qa_pixel")


def _max_days(parameters: dict[str, Any]) -> int:
    raw = parameters.get("max_days_apart")
    if raw is None:
        return DEFAULT_MAX_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError) as error:
        raise ToolExecutionError(f"max_days_apart must be a whole number of days, got {raw!r}.") from error
    if days < 0:
        raise ToolExecutionError("max_days_apart cannot be negative.")
    return days


def _split_pair(first: RasterDataset, second: RasterDataset) -> tuple[RasterDataset, RasterDataset]:
    """``(optical, sar)``, or a refusal when the pair is not one of each."""
    kinds = [is_sar(first), is_sar(second)]
    if kinds == [False, True]:
        return first, second
    if kinds == [True, False]:
        return second, first
    raise ToolExecutionError(
        "Fusion needs one optical and one SAR image; these are "
        + ("both SAR." if all(kinds) else "both optical.")
    )


def fuse(
    ndwi: BandArray, optical_threshold: float, decibels: Any, radar_valid: Any, radar_threshold: float
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    """Label every pixel by what each sensor said. Returns codes, counts, agreement."""
    size = ndwi.size
    if has_numpy():
        import numpy

        index = numpy.asarray(ndwi.values, dtype=numpy.float64)
        seen = numpy.isfinite(index)
        optical_water = seen & (index >= optical_threshold)
        db = numpy.asarray(decibels, dtype=numpy.float64)
        radar_ok = numpy.asarray(radar_valid, dtype=bool) & numpy.isfinite(db)
        radar_water = radar_ok & (db < radar_threshold)

        codes = numpy.zeros(size, dtype=numpy.uint8)
        both = radar_ok & seen
        codes[both & radar_water & optical_water] = WATER_BOTH
        codes[both & radar_water & ~optical_water] = WATER_RADAR_ONLY
        codes[both & ~radar_water & optical_water] = WATER_OPTICAL_ONLY
        codes[both & ~radar_water & ~optical_water] = LAND
        codes[radar_ok & ~seen & radar_water] = WATER_UNDER_CLOUD
        codes[radar_ok & ~seen & ~radar_water] = LAND
        codes[~radar_ok & seen & optical_water] = WATER_OPTICAL_ONLY
        codes[~radar_ok & seen & ~optical_water] = LAND
        counts = {label: int((codes == code).sum()) for code, label in CLASS_LABELS.items()}
        n = int(both.sum())
        radar_yes = int((both & radar_water).sum())
        optical_yes = int((both & optical_water).sum())
        agree = int((both & (radar_water == optical_water)).sum())
    else:
        codes = new_sample_buffer("uint8", size, CLASS_NODATA)
        counts = {label: 0 for label in CLASS_LABELS.values()}
        n = radar_yes = optical_yes = agree = 0
        for i in range(size):
            value = float(ndwi.values[i])
            seen_i = math.isfinite(value)
            optical_i = seen_i and value >= optical_threshold
            db_i = float(decibels[i])
            radar_ok_i = bool(radar_valid[i]) and math.isfinite(db_i)
            radar_i = radar_ok_i and db_i < radar_threshold
            if radar_ok_i and seen_i:
                code = (WATER_BOTH if optical_i else WATER_RADAR_ONLY) if radar_i else (
                    WATER_OPTICAL_ONLY if optical_i else LAND
                )
                n += 1
                radar_yes += radar_i
                optical_yes += optical_i
                agree += radar_i == optical_i
            elif radar_ok_i:
                code = WATER_UNDER_CLOUD if radar_i else LAND
            elif seen_i:
                code = WATER_OPTICAL_ONLY if optical_i else LAND
            else:
                continue
            codes[i] = code
            counts[CLASS_LABELS[code]] += 1

    agreement: dict[str, Any] = {"pixels_seen_by_both": n}
    if n:
        observed = agree / n
        p_radar, p_optical = radar_yes / n, optical_yes / n
        expected = p_radar * p_optical + (1 - p_radar) * (1 - p_optical)
        agreement["observed_agreement"] = observed
        agreement["kappa"] = (observed - expected) / (1 - expected) if expected < 1 else None
    return codes, counts, agreement


class OpticalSARFusionTool(RemoteSensingTool):
    """Fuses an optical and a SAR image into one annotated water map."""

    tool_id = "optical_sar_fusion"
    result_type = "fusion_water_map"

    def preflight(self, request: ToolRequest) -> None:
        SARAnalysisTool().preflight(request)
        numeric_parameter(request.parameters, "water_threshold", DEFAULT_OPTICAL_WATER_THRESHOLD)
        _max_days(request.parameters)

    def execute(self, request: ToolRequest) -> ToolOutput:
        self.preflight(request)
        parameters = request.parameters
        if len(request.input_references) != 2:
            raise ToolExecutionError(
                f"Fusion needs exactly two images, one optical and one SAR, but "
                f"{len(request.input_references)} were supplied."
            )
        log = StepLog()

        with log.step("open", "read both images, check the pair, clip"):
            try:
                first, second = (open_raster(path) for path in request.input_references)
            except RasterError as error:
                raise ToolExecutionError(str(error)) from error
            optical, radar = _split_pair(first, second)
            require_aligned(optical, radar)
            timing = self._check_dates(optical, radar, _max_days(parameters))
            aoi = None
            area = area_from_parameters(parameters)
            if area is not None:
                window = window_for(optical, area)
                full = optical
                optical, radar = clip(optical, window), clip(radar, window)
                aoi = describe_clip(full, optical, area, window)

        mask_band = parameters.get("mask_band") or next(
            (band.name for band in optical.bands if normalise(band.name) in CLOUD_MASK_BANDS), None
        )
        optical_threshold = numeric_parameter(parameters, "water_threshold", DEFAULT_OPTICAL_WATER_THRESHOLD)
        with log.step("optical_water", f"NDWI >= {optical_threshold:g}, cloud mask: {mask_band or 'none'}"):
            ndwi = compute_index(
                optical, NDWI_SPEC, {**parameters, "mask_band": mask_band},
                parameters.get("sensor") or optical.metadata.get("sensor"),
            )

        band = resolve_polarisation(radar, parameters.get("polarisation"))
        units, speckle_filter, window_size = calibration_options(parameters)
        with log.step("radar_water", f"{band.name} to dB, speckle filter {speckle_filter}"):
            decibels, valid, read_as = calibrated_decibels(
                band, radar.width, radar.height, units, speckle_filter, window_size
            )
            radar_threshold, radar_description, _ = water_threshold(
                decibels, valid, normalise(band.name), parameters
            )

        with log.step("fuse", "label each pixel by what each sensor saw"):
            codes, counts, agreement = fuse(ndwi.band, optical_threshold, decibels, valid, radar_threshold)
            fused_band = BandArray(
                name="fused_water", width=optical.width, height=optical.height,
                values=codes, dtype="uint8", nodata=float(CLASS_NODATA),
            )
            located = class_locations(codes, CLASS_LABELS, optical)

        observed = sum(counts.values())
        classes = {
            label: {"pixels": count, "fraction": count / observed if observed else 0.0}
            for label, count in counts.items()
        }
        water_pixels = sum(counts[label] for label in WATER_LABELS)
        statistics: dict[str, Any] = {
            "valid_pixels": observed,
            "total_pixels": optical.width * optical.height,
            "nodata_pixels": optical.width * optical.height - observed,
            "valid_fraction": observed / float(optical.width * optical.height),
            "water_pixels": water_pixels,
            "water_fraction": water_pixels / observed if observed else 0.0,
            "optical_masked_fraction": (ndwi.mask_report or {}).get("masked_fraction", 0.0),
            **agreement,
        }
        attach_areas(classes, statistics, optical)

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            with log.step("write", "fused map and both pictures"):
                artifacts = [
                    write_result_raster(
                        request=request, dataset=optical, band=fused_band,
                        source_path=optical.path or "optical", suffix="fused_water",
                        artifact_id="fusion_raster",
                        description=(
                            "Single-band uint8 fused water map: 0 = nodata, 1 = water "
                            "(both sensors), 2 = water (radar only), 3 = water (optical "
                            "only), 4 = water (radar, optical masked), 5 = land."
                        ),
                        dtype="uint8", nodata=0,
                    ),
                    write_preview(request, optical, optical.path or "optical"),
                    write_preview(request, radar, radar.path or "radar", "radar_preview"),
                ]

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "method": "optical_sar_water_fusion",
                "classes": classes,
                "class_codes": {str(code): label for code, label in CLASS_LABELS.items()},
                "class_locations": located,
                "optical_rule": f"NDWI >= {optical_threshold:g}",
                "radar_rule": f"{band.name} below the {radar_description}",
                "polarisation": band.name.upper(),
                "input_units": read_as,
                "speckle_filter": (
                    f"{window_size}x{window_size} boxcar on linear power"
                    if speckle_filter == "boxcar" else "none"
                ),
                "cloud_mask": mask_band,
                **timing,
                "interpretation": (
                    "Water both sensors saw is the most reliable. Radar-only water can "
                    "be flooded vegetation or a radar false alarm (smooth tarmac, shadow); "
                    "optical-only water can be wind-roughened water radar reads as land. "
                    "Water under cloud is seen by radar alone and cannot be confirmed "
                    "optically."
                ),
            },
            statistics=statistics,
            artifacts=artifacts,
            metadata={
                "source": optical.describe(),
                "radar": radar.describe(),
                "sensor": optical.metadata.get("sensor"),
                "mask": ndwi.mask_report,
                "aoi": aoi,
                "footprint_lonlat": footprint_lonlat(optical),
                "steps": log.steps,
                **backend_report(),
            },
        )

    @staticmethod
    def _check_dates(optical: RasterDataset, radar: RasterDataset, max_days: int) -> dict[str, Any]:
        optical_date, radar_date = find_acquisition_date(optical), find_acquisition_date(radar)
        if optical_date is None or radar_date is None:
            return {
                "optical_date": optical_date.isoformat() if optical_date else None,
                "radar_date": radar_date.isoformat() if radar_date else None,
                "days_apart": None,
            }
        gap = abs((optical_date - radar_date).days)
        if gap > max_days:
            raise ToolExecutionError(
                f"The optical image ({optical_date}) and the SAR image ({radar_date}) "
                f"are {gap} days apart; fusion needs them within {max_days} days, or "
                "they describe different conditions on the ground."
            )
        return {
            "optical_date": optical_date.isoformat(),
            "radar_date": radar_date.isoformat(),
            "days_apart": gap,
        }


__all__ = ["CLASS_LABELS", "OpticalSARFusionTool", "fuse"]
