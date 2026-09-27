"""Tests for region labelling and region-based object detection."""

from __future__ import annotations

import pytest

from app.tools.base import ToolRequest, UnsupportedRequestError
from app.tools.detection import regions as regions_module
from app.tools.detection.regions import find_runs, label_regions
from app.tools.detection.tool import RegionDetectionTool, resolve_targets
from app.tools.raster.io import open_raster
from tests.conftest import make_band


def label(grid, targets, connectivity=8):
    height, width = len(grid), len(grid[0])
    flat = [value for row in grid for value in row]
    runs = find_runs(flat, width, height, set(targets))
    return label_regions(runs, height, connectivity)[0]


# ============================================================
# LABELLING
# ============================================================
GRID = [
    [1, 1, 0, 0, 0],
    [1, 1, 0, 0, 0],
    [0, 0, 1, 0, 2],
    [0, 0, 0, 0, 2],
    [2, 2, 0, 0, 2],
]


def test_eight_connectivity_joins_diagonal_neighbours():
    found = label(GRID, {1, 2}, connectivity=8)
    assert [(r.group, r.pixels) for r in found] == [(1, 5), (2, 3), (2, 2)]


def test_four_connectivity_does_not():
    found = label(GRID, {1, 2}, connectivity=4)
    assert sorted((r.group, r.pixels) for r in found) == [(1, 1), (1, 4), (2, 2), (2, 3)]


def test_only_requested_classes_are_labelled():
    assert [(r.group, r.pixels) for r in label(GRID, {2})] == [(2, 3), (2, 2)]


def test_a_diagonal_link_across_another_class_is_found():
    # Class 2 touches itself only at a corner, with class 1 in between. A
    # merge that advances both rows together when their runs end at the same
    # column misses this link.
    grid = [
        [2, 2, 0, 0],
        [1, 1, 2, 2],
    ]
    assert sorted((r.group, r.pixels) for r in label(grid, {1, 2})) == [(1, 2), (2, 4)]
    assert sorted((r.group, r.pixels) for r in label(grid, {1, 2}, 4)) == [(1, 2), (2, 2), (2, 2)]


def test_extent_and_centroid_are_exact():
    region = label(GRID, {1})[0]
    assert (region.col_min, region.row_min, region.col_max, region.row_max) == (0, 0, 2, 2)
    # Pixels (0,0) (0,1) (1,0) (1,1) (2,2): mean column 0.8, mean row 0.8.
    assert region.centroid == pytest.approx((0.8, 0.8))


def test_both_backends_find_the_same_runs(monkeypatch):
    flat = [value for row in GRID for value in row]
    fast = find_runs(flat, 5, 5, {1, 2})
    monkeypatch.setattr(regions_module, "has_numpy", lambda: False)
    slow = find_runs(flat, 5, 5, {1, 2})
    assert fast == slow


# ============================================================
# TARGETS
# ============================================================
def test_no_target_means_every_object_type():
    targets, unresolvable = resolve_targets(None)
    assert len(targets) == 5
    assert unresolvable == []


def test_words_map_onto_object_types():
    targets, _ = resolve_targets(["water bodies", "lakes"])
    assert targets == [1]


def test_objects_too_small_to_resolve_are_refused_with_an_alternative():
    with pytest.raises(UnsupportedRequestError, match="sub-metre imagery") as error:
        resolve_targets(["buildings", "roads"])
    assert "water bodies" in str(error.value)


def test_a_mixed_request_keeps_what_it_can_and_reports_the_rest():
    targets, unresolvable = resolve_targets(["water", "ships"])
    assert targets == [1]
    assert unresolvable == ["ships"]


# ============================================================
# THE TOOL
# ============================================================
@pytest.fixture
def lakes(raster_factory):
    """A 6x4 scene: two separate lakes (3 and 2 pixels) in dense vegetation."""
    water = {(0, 0), (0, 1), (1, 0), (3, 4), (3, 5)}
    green, red, nir, swir = [], [], [], []
    for row in range(4):
        for col in range(6):
            if (row, col) in water:
                g, r, n, s = 1000, 600, 200, 100
            else:
                g, r, n, s = 800, 500, 4000, 1500
            green.append(g)
            red.append(r)
            nir.append(n)
            swir.append(s)
    bands = [
        make_band("B3", green, 6, 4),
        make_band("B4", red, 6, 4),
        make_band("B8", nir, 6, 4),
        make_band("B11", swir, 6, 4),
    ]
    return raster_factory("lakes.tif", bands)


def detect(path, tmp_path, **parameters):
    return RegionDetectionTool().execute(
        ToolRequest(
            tool_id="object_detection",
            input_references=[path],
            parameters=parameters,
            output_directory=str(tmp_path / "out"),
        )
    )


def test_each_lake_is_one_object_with_its_own_extent(lakes, tmp_path):
    output = detect(lakes, tmp_path, target_objects=["lakes"], min_area_pixels=1)

    assert output.data["counts"] == {"water_body": 2}
    first, second = output.data["detections"]
    assert (first["pixels"], second["pixels"]) == (3, 2)
    assert first["bbox_pixels"] == [0, 0, 1, 1]
    assert second["bbox_pixels"] == [4, 3, 5, 3]
    # 10 m pixels from origin (699960, 2100000): columns 4-5, row 3.
    assert second["bbox"] == [700000.0, 2099960.0, 700020.0, 2099970.0]
    assert second["area_square_units"] == pytest.approx(200.0)
    assert "confidence" not in first


def test_small_regions_are_dropped_and_counted(lakes, tmp_path):
    output = detect(lakes, tmp_path, target_objects=["water"], min_area_pixels=3)
    assert output.data["counts"] == {"water_body": 1}
    assert output.statistics["regions_below_minimum"] == 1


def test_the_object_rasters_match_the_list(lakes, tmp_path):
    output = detect(lakes, tmp_path, target_objects=["water"], min_area_pixels=1)
    by_id = {artifact.artifact_id: artifact.path for artifact in output.artifacts}

    types = [int(v) for v in open_raster(by_id["detections_raster"]).bands[0].values]
    ids = [int(v) for v in open_raster(by_id["detection_ids_raster"]).bands[0].values]
    assert types.count(1) == 5
    assert ids.count(1) == 3 and ids.count(2) == 2
    assert ids[0] == 1 and ids[3 * 6 + 5] == 2


def test_an_unresolvable_request_is_refused_before_reading_pixels(tmp_path):
    tool = RegionDetectionTool()
    with pytest.raises(UnsupportedRequestError):
        tool.preflight(
            ToolRequest(tool_id="object_detection", parameters={"target_objects": ["cars"]})
        )


def test_singular_and_plural_are_one_request():
    with pytest.raises(UnsupportedRequestError) as error:
        resolve_targets(["buildings", "building"])
    assert "Detecting buildings needs" in str(error.value)
