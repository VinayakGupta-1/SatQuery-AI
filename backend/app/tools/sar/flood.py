"""Flooding as *new* water: a flood-period scene against a dry-season reference.

A single radar scene shows where water is, not where it should not be. Asked
"what flooded near Kochi?", a one-scene water map counts the Arabian Sea and
the backwaters too, and calls half the area flooded.

Given a reference scene from the dry season as well, both are mapped with the
**same** threshold and every pixel falls in one of four classes::

    flooded          water now,  dry in the reference   <- the answer
    permanent_water  water in both                        rivers, lakes, sea
    receded_water    water in the reference, dry now
    dry_land         dry in both

Using one threshold for both dates matters: thresholding each scene
separately would let a difference in threshold masquerade as a flood.
"""

from __future__ import annotations

import math
from typing import Any

from app.tools.base import Artifact, StepLog, ToolExecutionError, ToolOutput, ToolRequest
from app.tools.change.alignment import order_by_acquisition, require_aligned
from app.tools.indices.index_tool import attach_areas, write_result_raster
from app.tools.raster.aoi import footprint_lonlat, open_for_analysis
from app.tools.raster.backends import has_numpy
from app.tools.raster.bands import normalise
from app.tools.raster.io import backend_report
from app.tools.raster.locate import class_locations
from app.tools.raster.model import BandArray, new_sample_buffer
from app.tools.raster.render import write_preview
from app.tools.sar.backscatter import (
    NON_WATER,
    WATER,
    calibrated_decibels,
    classify_water,
    resolve_polarisation,
    summarise_decibels,
)

FLOODED, PERMANENT, RECEDED, DRY = 1, 2, 3, 4
FLOOD_LABELS = {
    FLOODED: "flooded",
    PERMANENT: "permanent_water",
    RECEDED: "receded_water",
    DRY: "dry_land",
}


def flood_classes(reference: BandArray, event: BandArray) -> tuple[BandArray, dict[str, int]]:
    """Combine two water maps (1 water, 2 not, 0 nodata) into flood classes."""
    width, height = event.width, event.height
    if has_numpy():
        import numpy

        before = numpy.asarray(reference.values)
        after = numpy.asarray(event.values)
        codes = numpy.zeros(after.shape, dtype=numpy.uint8)
        seen = (before != 0) & (after != 0)
        codes[seen & (after == WATER) & (before == NON_WATER)] = FLOODED
        codes[seen & (after == WATER) & (before == WATER)] = PERMANENT
        codes[seen & (after == NON_WATER) & (before == WATER)] = RECEDED
        codes[seen & (after == NON_WATER) & (before == NON_WATER)] = DRY
        counts = {label: int((codes == code).sum()) for code, label in FLOOD_LABELS.items()}
    else:
        codes = new_sample_buffer("uint8", width * height, 0)
        counts = {label: 0 for label in FLOOD_LABELS.values()}
        table = {
            (NON_WATER, WATER): FLOODED,
            (WATER, WATER): PERMANENT,
            (WATER, NON_WATER): RECEDED,
            (NON_WATER, NON_WATER): DRY,
        }
        for index, pair in enumerate(zip(reference.values, event.values)):
            code = table.get((int(pair[0]), int(pair[1])))
            if code:
                codes[index] = code
                counts[FLOOD_LABELS[code]] += 1
    band = BandArray(
        name="sar_flood", width=width, height=height, values=codes, dtype="uint8", nodata=0.0
    )
    return band, counts


def execute_flood(
    tool_id: str,
    request: ToolRequest,
    calibration: tuple[str, str, int],
    threshold_for: Any,
) -> ToolOutput:
    """Map flooding from a reference and a flood-period scene.

    ``threshold_for(decibels, valid, polarisation)`` returns the water
    threshold; it is computed on the flood-period scene, where the water to be
    separated is, and applied unchanged to the reference.
    """
    parameters = request.parameters
    first_path, second_path = request.input_references
    log = StepLog()
    with log.step("open", "read and clip both scenes"):
        first, aoi = open_for_analysis(first_path, parameters)
        second, _ = open_for_analysis(second_path, parameters)
    reference, event, ordering = order_by_acquisition(first, second)
    require_aligned(reference, event)
    if ordering.get("temporal_order_source") != "acquisition_date":
        raise ToolExecutionError(
            "Mapping a flood needs to know which scene is the dry reference: both "
            "images must carry acquisition dates."
        )

    requested = parameters.get("polarisation")
    reference_band = resolve_polarisation(reference, requested)
    event_band = resolve_polarisation(event, requested or reference_band.name)
    polarisation = normalise(event_band.name)

    units, speckle_filter, window = calibration
    with log.step("calibrate", f"{event_band.name} to dB on both dates, speckle filter {speckle_filter}"):
        event_db, event_valid, detected = calibrated_decibels(
            event_band, event.width, event.height, units, speckle_filter, window
        )
        reference_db, reference_valid, _ = calibrated_decibels(
            reference_band, reference.width, reference.height, units, speckle_filter, window
        )

    threshold, threshold_description, method = threshold_for(event_db, event_valid, polarisation)
    if not math.isfinite(threshold):
        raise ToolExecutionError("No water threshold could be derived from the flood-period scene.")

    with log.step("classify", f"one {threshold_description} applied to both dates"):
        event_water, _ = classify_water(event_db, event_valid, threshold, event.width, event.height)
        reference_water, _ = classify_water(
            reference_db, reference_valid, threshold, reference.width, reference.height
        )
        flood_map, counts = flood_classes(reference_water, event_water)
        locations = class_locations(flood_map.values, {FLOODED: "flooded"}, event)

    valid_pixels = sum(counts.values())
    total = event.width * event.height
    classes = {
        label: {"pixels": count, "fraction": count / valid_pixels if valid_pixels else 0.0}
        for label, count in counts.items()
    }
    statistics: dict[str, Any] = {
        **summarise_decibels(event_db, event_valid),
        "valid_pixels": valid_pixels,
        "nodata_pixels": total - valid_pixels,
        "total_pixels": total,
        "valid_fraction": valid_pixels / total if total else 0.0,
        "flooded_pixels": counts["flooded"],
        "flooded_fraction": classes["flooded"]["fraction"],
        "permanent_water_fraction": classes["permanent_water"]["fraction"],
    }
    attach_areas(classes, statistics, event)

    artifacts: list[Artifact] = []
    if parameters.get("write_raster", True):
        with log.step("write", "flood map and scene picture"):
            artifacts = [
                write_result_raster(
                    request=request,
                    dataset=event,
                    band=flood_map,
                    source_path=event.path or second_path,
                    suffix="sar_flood",
                    artifact_id="sar_flood_raster",
                    description=(
                        "Single-band uint8 flood map: 0 = nodata, 1 = flooded (water now, "
                        "dry in the reference), 2 = permanent water, 3 = receded water, "
                        f"4 = dry land. {polarisation.upper()} below {threshold:.2f} dB is water "
                        "on both dates."
                    ),
                    dtype="uint8",
                    nodata=0,
                ),
                write_preview(request, event, event.path or "event"),
            ]

    return ToolOutput(
        tool_id=tool_id,
        result_type="sar_flood_map",
        data={
            "method": "sar_flood_change",
            "polarisation": polarisation.upper(),
            "input_units": detected,
            "threshold": threshold,
            "threshold_method": method,
            "threshold_description": threshold_description,
            "speckle_filter": (
                f"{window}x{window} boxcar on linear power" if speckle_filter == "boxcar" else "none"
            ),
            "reference_date": ordering["earlier_date"],
            "event_date": ordering["later_date"],
            "classes": classes,
            "class_locations": locations,
            "class_codes": {str(code): label for code, label in FLOOD_LABELS.items()},
            "interpretation": (
                "Flooded means open water in the flood-period scene where the dry-season "
                "reference was dry. Water present on both dates -- rivers, lakes, the sea -- "
                "is permanent and not counted as flood. Wind-roughened water can read as "
                "land, and radar shadow or wet tarmac as water."
            ),
        },
        statistics=statistics,
        artifacts=artifacts,
        metadata={
            "earlier": reference.describe(),
            "later": event.describe(),
            "sensor": event.metadata.get("sensor"),
            "aoi": aoi,
            "footprint_lonlat": footprint_lonlat(event),
            "steps": log.steps,
            **backend_report(),
        },
    )


__all__ = ["FLOOD_LABELS", "execute_flood", "flood_classes"]
