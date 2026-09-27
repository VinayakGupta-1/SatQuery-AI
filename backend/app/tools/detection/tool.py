"""Object detection as region extraction.

At the 10-30 m resolution of Sentinel-2 and Landsat, a building, a car or a
ship is a pixel or less: detecting it needs sub-metre imagery and a trained
detector, and this deployment has neither. What *is* resolvable at that scale
are discrete landscape objects -- a lake, a reservoir, a settlement, a forest
patch, a clearing -- and those are what this tool finds.

It classifies the scene with the land-cover rules
(:mod:`app.tools.landcover`), then extracts every connected region of the
requested classes as one object, with its area, bounding box and centroid.
Asked for something it cannot resolve, it says so instead of labelling a
built-up blob "building".
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
    UnsupportedRequestError,
)
from app.tools.detection.regions import Region, find_runs, label_regions
from app.tools.landcover.classifier import (
    BARE_OR_BUILT_UP,
    BARE_SOIL,
    BUILT_UP,
    CODES_WITH_SWIR,
    CODES_WITHOUT_SWIR,
    DENSE_VEGETATION,
    SPARSE_VEGETATION,
    WATER,
)
from app.tools.landcover.tool import classify_dataset, thresholds_from
from app.tools.raster.backends import has_numpy
from app.tools.raster.aoi import footprint_lonlat, open_for_analysis, pixel_to_lonlat
from app.tools.raster.io import backend_report, write_raster
from app.tools.raster.model import BandArray, RasterError, new_sample_buffer
from app.tools.raster.render import write_preview

#: Object types, as codes in the output raster. 0 is background.
WATER_BODY = 1
VEGETATION_PATCH = 2
BUILT_UP_CLUSTER = 3
BARE_LAND_PATCH = 4
BARE_OR_BUILT_UP_PATCH = 5

OBJECT_LABELS: dict[int, str] = {
    WATER_BODY: "water_body",
    VEGETATION_PATCH: "vegetation_patch",
    BUILT_UP_CLUSTER: "built_up_cluster",
    BARE_LAND_PATCH: "bare_land_patch",
    BARE_OR_BUILT_UP_PATCH: "bare_or_built_up_patch",
}

#: Which land-cover classes make up each object type. Dense and sparse
#: vegetation are one patch: a wood does not stop where its canopy thins.
LAND_COVER_TO_OBJECT: dict[int, int] = {
    WATER: WATER_BODY,
    DENSE_VEGETATION: VEGETATION_PATCH,
    SPARSE_VEGETATION: VEGETATION_PATCH,
    BUILT_UP: BUILT_UP_CLUSTER,
    BARE_SOIL: BARE_LAND_PATCH,
    BARE_OR_BUILT_UP: BARE_OR_BUILT_UP_PATCH,
}

#: Words a request may use for each object type.
TARGET_WORDS: dict[str, int] = {
    **dict.fromkeys(
        ["water", "water bodies", "water body", "lake", "lakes", "pond", "ponds",
         "reservoir", "reservoirs", "river", "rivers"],
        WATER_BODY,
    ),
    **dict.fromkeys(
        ["vegetation", "forest", "forests", "trees", "woodland", "green cover",
         "vegetation patches", "vegetation patch"],
        VEGETATION_PATCH,
    ),
    **dict.fromkeys(
        ["built-up", "built up", "urban", "urban area", "urban areas",
         "settlement", "settlements", "town", "towns", "village", "villages"],
        BUILT_UP_CLUSTER,
    ),
    **dict.fromkeys(
        ["bare soil", "bare land", "bare ground", "clearing", "clearings",
         "cleared land", "barren land"],
        BARE_LAND_PATCH,
    ),
}

#: Objects that are real targets for detection but not at this resolution.
UNRESOLVABLE = {
    "building", "buildings", "road", "roads", "ship", "ships", "boat", "boats",
    "vehicle", "vehicles", "car", "cars", "aircraft", "plane", "planes",
    "airplane", "airplanes",
}

DEFAULT_MIN_AREA_PIXELS = 9
DEFAULT_MAX_OBJECTS = 100


def _integer(parameters: dict[str, Any], name: str, default: int, low: int, high: int) -> int:
    raw = parameters.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ToolExecutionError(f"{name} must be an integer, got {raw!r}.") from error
    if not low <= value <= high:
        raise ToolExecutionError(f"{name} must be between {low} and {high}, got {value}.")
    return value


def resolve_targets(raw: Any) -> tuple[list[int], list[str]]:
    """Map requested words to object types.

    Returns ``(object_types, unresolvable_words)``. No request means every
    object type. A request made only of objects that cannot be resolved at
    this scale raises :class:`UnsupportedRequestError`.
    """
    if raw is None or raw == "" or raw == []:
        return sorted(set(LAND_COVER_TO_OBJECT.values())), []
    words = [raw] if isinstance(raw, str) else [str(item) for item in raw]

    targets: set[int] = set()
    unresolvable: list[str] = []
    stems: set[str] = set()
    for word in words:
        key = word.strip().lower()
        if key in TARGET_WORDS:
            targets.add(TARGET_WORDS[key])
        elif key in UNRESOLVABLE:
            # "buildings" and "building" are one request, named once.
            stem = key.rstrip("s")
            if stem not in stems:
                stems.add(stem)
                unresolvable.append(key)

    if not targets:
        if unresolvable:
            raise UnsupportedRequestError(
                f"Detecting {', '.join(unresolvable)} needs sub-metre imagery and a "
                "trained object detector, which this deployment does not have; at "
                "10-30 m each one is a pixel or less. What can be detected at this "
                "scale is discrete landscape objects: water bodies, vegetation "
                "patches, built-up clusters and bare-land patches. Ask for one of "
                "those, for example 'How many water bodies are there?'."
            )
        raise UnsupportedRequestError(
            f"None of {words} is an object type this tool can extract. It detects "
            "water bodies, vegetation patches, built-up clusters and bare-land "
            "patches."
        )
    # Without SWIR, bare land and built-up land are one class, so a request for
    # either is answered with the merged object type as well.
    if targets & {BUILT_UP_CLUSTER, BARE_LAND_PATCH}:
        targets.add(BARE_OR_BUILT_UP_PATCH)
    return sorted(targets), unresolvable


class RegionDetectionTool(RemoteSensingTool):
    """Extracts discrete landscape objects as connected land-cover regions."""

    tool_id = "object_detection"
    result_type = "detections"

    def preflight(self, request: ToolRequest) -> None:
        parameters = request.parameters
        resolve_targets(parameters.get("target_objects"))
        thresholds_from(parameters)
        _integer(parameters, "min_area_pixels", DEFAULT_MIN_AREA_PIXELS, 1, 10_000_000)
        _integer(parameters, "max_objects", DEFAULT_MAX_OBJECTS, 1, 1000)
        if _integer(parameters, "connectivity", 8, 4, 8) not in (4, 8):
            raise ToolExecutionError("connectivity must be 4 or 8.")

    def execute(self, request: ToolRequest) -> ToolOutput:
        self.preflight(request)
        parameters = request.parameters
        targets, unresolvable = resolve_targets(parameters.get("target_objects"))
        min_area = _integer(parameters, "min_area_pixels", DEFAULT_MIN_AREA_PIXELS, 1, 10_000_000)
        max_objects = _integer(parameters, "max_objects", DEFAULT_MAX_OBJECTS, 1, 1000)
        connectivity = _integer(parameters, "connectivity", 8, 4, 8)

        path = self.require_single_input(request)
        log = StepLog()
        with log.step("open", "read and clip the imagery"):
            dataset, aoi = open_for_analysis(path, parameters)

        with log.step("classify", "land-cover rules per pixel"):
            classification = classify_dataset(dataset, parameters)
        land_cover = classification.result
        width, height = dataset.width, dataset.height

        # Only object types this scene can actually contain are searched: with
        # SWIR the merged bare/built-up class never occurs, without it the two
        # separate classes never do.
        palette = CODES_WITH_SWIR if land_cover.has_swir else CODES_WITHOUT_SWIR
        present = {LAND_COVER_TO_OBJECT[code] for code in palette}
        searched = [target for target in targets if target in present]

        with log.step("label", f"connected regions, {connectivity}-connectivity"):
            objects = _object_types(land_cover.band.values)
            runs = find_runs(objects, width, height, set(searched))
            regions, membership = label_regions(runs, height, connectivity)

        kept = sorted(
            (index for index, region in enumerate(regions) if region.pixels >= min_area),
            key=lambda index: (-regions[index].pixels, index),
        )
        object_id = {region_index: rank for rank, region_index in enumerate(kept, start=1)}

        georeference = dataset.georeference
        pixel_area = georeference.pixel_area()
        records = [
            _record(rank, regions[index], dataset, pixel_area)
            for rank, index in enumerate(kept, start=1)
        ]

        counts = {OBJECT_LABELS[target]: 0 for target in searched}
        areas: dict[str, float] = {OBJECT_LABELS[target]: 0.0 for target in searched}
        object_pixels = 0
        for record in records:
            counts[record["label"]] += 1
            object_pixels += record["pixels"]
            if pixel_area is not None:
                areas[record["label"]] += record["area_square_units"]

        valid = land_cover.valid_pixels
        statistics: dict[str, Any] = {
            "objects_detected": len(records),
            "regions_below_minimum": len(regions) - len(kept),
            "object_pixels": object_pixels,
            "valid_pixels": valid,
            "nodata_pixels": land_cover.total_pixels - valid,
            "total_pixels": land_cover.total_pixels,
            "valid_fraction": valid / land_cover.total_pixels if land_cover.total_pixels else 0.0,
        }
        if pixel_area is not None:
            statistics["pixel_area_square_units"] = pixel_area
            statistics["valid_area_square_units"] = valid * pixel_area

        artifacts: list[Artifact] = []
        if parameters.get("write_raster", True):
            with log.step("write", "object rasters and scene picture"):
                artifacts = self._write_outputs(
                    request, dataset, path, runs, membership, object_id, width, height
                )
                artifacts.append(write_preview(request, dataset, path))

        return ToolOutput(
            tool_id=self.tool_id,
            result_type=self.result_type,
            data={
                "method": "connected_land_cover_regions",
                "targets": [OBJECT_LABELS[target] for target in searched],
                "unresolvable_targets": unresolvable,
                "detections": records[:max_objects],
                "detections_total": len(records),
                "detections_returned": min(len(records), max_objects),
                "counts": counts,
                "areas_square_units": areas if pixel_area is not None else {},
                "min_area_pixels": min_area,
                "connectivity": connectivity,
                "class_codes": {
                    str(code): label for code, label in OBJECT_LABELS.items()
                    if code in searched
                },
                "classification_rules": classification.thresholds.describe(
                    land_cover.has_swir
                ),
                "interpretation": (
                    "Each object is a connected patch of one land-cover class, "
                    "classified with transparent spectral-index rules. It is not "
                    "the output of a trained object detector, so it carries no "
                    "detection confidence."
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

    @staticmethod
    def _write_outputs(request, dataset, path, runs, membership, object_id, width, height):
        size = width * height
        if has_numpy():
            import numpy

            types = numpy.zeros(size, dtype=numpy.uint8)
            ids = numpy.zeros(size, dtype=numpy.uint32)
            for run, region_index in zip(runs, membership):
                identifier = object_id.get(region_index)
                if identifier is None:
                    continue
                offset = run.row * width
                types[offset + run.start: offset + run.end] = run.group
                ids[offset + run.start: offset + run.end] = identifier
        else:
            types = new_sample_buffer("uint8", size, 0)
            ids = new_sample_buffer("uint32", size, 0)
            for run, region_index in zip(runs, membership):
                identifier = object_id.get(region_index)
                if identifier is None:
                    continue
                offset = run.row * width
                for column in range(run.start, run.end):
                    types[offset + column] = run.group
                    ids[offset + column] = identifier

        directory = request.resolved_output_directory()
        stem = os.path.splitext(os.path.basename(path))[0]
        type_path = os.path.join(directory, f"{stem}_objects.tif")
        id_path = os.path.join(directory, f"{stem}_object_ids.tif")
        metadata = {"sensor": dataset.metadata.get("sensor")}
        legend = ", ".join(f"{code} = {label.replace('_', ' ')}" for code, label in OBJECT_LABELS.items())
        try:
            write_raster(
                type_path,
                [BandArray("object_type", width, height, types, dtype="uint8", nodata=0.0)],
                dataset.georeference, dtype="uint8", nodata=0, metadata=metadata,
            )
            write_raster(
                id_path,
                [BandArray("object_id", width, height, ids, dtype="uint32", nodata=0.0)],
                dataset.georeference, dtype="uint32", nodata=0, metadata=metadata,
            )
        except RasterError as error:
            raise ToolExecutionError(
                f"Objects were detected but could not be written: {error}"
            ) from error

        return [
            Artifact(
                artifact_id="detections_raster",
                kind="raster",
                path=type_path,
                format="GTiff",
                description=f"Single-band uint8 map of detected objects: 0 = background, {legend}.",
            ),
            Artifact(
                artifact_id="detection_ids_raster",
                kind="raster",
                path=id_path,
                format="GTiff",
                description=(
                    "Single-band uint32 raster of object ids matching the detection "
                    "list (1 = largest); 0 = background."
                ),
            ),
        ]


def _object_types(land_cover: Any) -> Any:
    """Map every land-cover code to its object type (0 where there is none)."""
    if has_numpy():
        import numpy

        table = numpy.zeros(256, dtype=numpy.uint8)
        for code, object_type in LAND_COVER_TO_OBJECT.items():
            table[code] = object_type
        return table[numpy.asarray(land_cover, dtype=numpy.uint8)]
    return [LAND_COVER_TO_OBJECT.get(int(code), 0) for code in land_cover]


def _record(identifier: int, region: Region, dataset: Any, pixel_area: float | None) -> dict[str, Any]:
    """Describe one region in pixel space and, when georeferenced, map space."""
    georeference = dataset.georeference
    col, row = region.centroid
    record: dict[str, Any] = {
        "id": identifier,
        "label": OBJECT_LABELS[region.group],
        "pixels": region.pixels,
        # Inclusive pixel indices: [first column, first row, last column, last row].
        "bbox_pixels": [region.col_min, region.row_min, region.col_max, region.row_max],
        "centroid_pixel": [round(col, 2), round(row, 2)],
    }
    transform = georeference.transform if georeference.is_georeferenced else None
    if transform is not None:
        origin_x, pixel_w, _, origin_y, _, pixel_h = transform
        xs = (origin_x + region.col_min * pixel_w, origin_x + (region.col_max + 1) * pixel_w)
        ys = (origin_y + region.row_min * pixel_h, origin_y + (region.row_max + 1) * pixel_h)
        record["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
        record["centroid"] = [
            origin_x + (col + 0.5) * pixel_w,
            origin_y + (row + 0.5) * pixel_h,
        ]
        lonlat = pixel_to_lonlat(dataset, col, row)
        if lonlat is not None:
            record["centroid_lonlat"] = [round(lonlat[0], 5), round(lonlat[1], 5)]
    if pixel_area is not None:
        record["area_square_units"] = region.pixels * pixel_area
    return record


__all__ = ["OBJECT_LABELS", "RegionDetectionTool", "resolve_targets"]
