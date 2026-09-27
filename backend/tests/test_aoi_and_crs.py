"""Tests for coordinate transforms, clipping to an area, and the checks around them."""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.schemas.errors import ErrorCode
from app.schemas.inputs import ImageInput
from app.schemas.spatiotemporal import AreaOfInterest, TimeRange
from app.schemas.task import InputRequirements
from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.indices.ndvi import NDVITool
from app.tools.raster import crs as crs_module
from app.tools.raster.aoi import area_from_parameters, clip, footprint_lonlat, window_for
from app.tools.raster.crs import CRSError, lonlat_to_utm, transform_bounds, transform_points, utm_to_lonlat
from app.tools.raster.inspection import describe_raster
from app.tools.raster.io import open_raster
from app.validator.validator import validate_inputs


# ============================================================
# COORDINATES
# ============================================================
@pytest.mark.parametrize(
    "lon, lat, zone, south",
    [(79.08, 21.14, 44, False), (72.87, 19.07, 43, False), (151.2, -33.9, 56, True)],
)
def test_the_transverse_mercator_series_round_trips(lon, lat, zone, south):
    x, y = lonlat_to_utm(lon, lat, zone, south)
    back_lon, back_lat = utm_to_lonlat(x, y, zone, south)
    assert back_lon == pytest.approx(lon, abs=1e-8)
    assert back_lat == pytest.approx(lat, abs=1e-8)


def test_the_series_agrees_with_proj_to_the_millimetre():
    rasterio = pytest.importorskip("rasterio")
    from rasterio.warp import transform

    xs, ys = transform("EPSG:4326", "EPSG:32644", [79.08], [21.14])
    x, y = lonlat_to_utm(79.08, 21.14, 44, False)
    assert math.hypot(x - xs[0], y - ys[0]) < 0.005
    assert rasterio  # imported for the skip above


def test_without_rasterio_only_wgs84_and_its_utm_zones_are_supported(monkeypatch):
    monkeypatch.setattr(crs_module, "has_rasterio", lambda: False)
    xs, ys = transform_points([79.08], [21.14], "EPSG:4326", "EPSG:32644")
    assert xs[0] == pytest.approx(lonlat_to_utm(79.08, 21.14, 44, False)[0])
    with pytest.raises(CRSError, match="needs rasterio"):
        transform_points([0], [0], "EPSG:4326", "EPSG:27700")


def test_bounds_are_densified_not_just_their_corners():
    # A whole-zone box: a line of constant northing is not a parallel, so the
    # northern edge bulges poleward at the central meridian and the corners
    # alone understate the extent.
    box = [166000.0, 2000000.0, 834000.0, 3000000.0]
    bounds = transform_bounds(box, "EPSG:32643", "EPSG:4326")
    corners = transform_bounds(box, "EPSG:32643", "EPSG:4326", densify=2)
    assert bounds[0] < bounds[2] and bounds[1] < bounds[3]
    assert bounds[3] > corners[3] + 0.01
    assert bounds[0] <= corners[0] and bounds[1] <= corners[1] and bounds[2] >= corners[2]


def test_a_utm_box_lands_where_the_zone_puts_it():
    # Zone 43's central meridian is 75 E; 199.96 km east of it at 19 N is ~76.9 E.
    west, south, _, _ = transform_bounds([699960, 2099960, 699980, 2100000], "EPSG:32643", "EPSG:4326")
    assert 76.85 < west < 76.95 and 18.95 < south < 19.0


# ============================================================
# WINDOWS AND CLIPPING
# ============================================================
def test_a_region_is_a_fraction_of_the_grid(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)
    window = window_for(dataset, AreaOfInterest(region="south_east"))
    assert (window.col_off, window.row_off, window.width, window.height) == (1, 1, 1, 1)


def test_clipping_keeps_values_and_moves_the_origin(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)
    clipped = clip(dataset, window_for(dataset, AreaOfInterest(region="south")))

    assert (clipped.width, clipped.height) == (2, 1)
    assert [float(v) for v in clipped.band("B4").values] == [3000.0, 500.0]
    # One 10 m row further south.
    assert clipped.georeference.transform[3] == pytest.approx(2100000.0 - 10.0)


def test_a_bbox_in_another_crs_is_transformed_before_clipping(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)
    lon, lat = utm_to_lonlat(699975.0, 2099985.0, 43, False)  # centre of pixel (1, 1)
    area = AreaOfInterest(bbox=[lon - 1e-5, lat - 1e-5, lon + 1e-5, lat + 1e-5])
    window = window_for(dataset, area)
    assert (window.col_off, window.row_off, window.width, window.height) == (1, 1, 1, 1)


def test_an_area_off_the_image_is_refused(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)
    with pytest.raises(ToolExecutionError, match="does not overlap"):
        window_for(dataset, AreaOfInterest(bbox=[10.0, 10.0, 10.1, 10.1]))


def test_area_parameters_are_checked():
    assert area_from_parameters({}) is None
    assert area_from_parameters({"aoi_region": "North-West"}).region == "north_west"
    assert area_from_parameters({"aoi_bbox": "1,2,3,4"}).bbox == [1.0, 2.0, 3.0, 4.0]
    with pytest.raises(ToolExecutionError, match="Unknown aoi_region"):
        area_from_parameters({"aoi_region": "upstairs"})
    with pytest.raises(ToolExecutionError, match="min below max"):
        area_from_parameters({"aoi_bbox": [3, 4, 1, 2]})


def test_a_tool_computes_only_over_the_area(sentinel2_scene, tmp_path):
    # NDVI per pixel is [0.5, 0.0, -0.5, 0.8]; the northern row is the first two.
    output = NDVITool().execute(
        ToolRequest(
            tool_id="ndvi",
            input_references=[sentinel2_scene],
            parameters={"aoi_region": "north", "write_raster": False},
            output_directory=str(tmp_path),
        )
    )
    assert output.statistics["total_pixels"] == 2
    assert output.statistics["mean"] == pytest.approx(0.25)
    assert output.metadata["aoi"]["fraction_of_scene"] == pytest.approx(0.5)
    assert output.metadata["aoi"]["bounds_lonlat"] is not None


def test_the_footprint_is_reported_in_degrees(sentinel2_scene):
    west, south, east, north = footprint_lonlat(open_raster(sentinel2_scene))
    assert 76.85 < west < east < 76.95 and 18.95 < south < north < 19.0


# ============================================================
# THE VALIDATOR ENFORCES WHERE AND WHEN
# ============================================================
def dated(path, day):
    metadata = describe_raster(path)
    metadata.acquisition_date = day
    return ImageInput(id="image_1", path=path, metadata=metadata)


def test_an_image_outside_the_requested_period_is_refused(sentinel2_scene):
    result = validate_inputs(
        [dated(sentinel2_scene, date(2019, 5, 1))],
        InputRequirements(time_range=TimeRange(start=date(2023, 1, 1), end=date(2025, 12, 31))),
    )
    assert not result.valid
    assert result.errors[0].code == ErrorCode.TEMPORAL_INCOMPATIBILITY
    assert "outside the period" in result.errors[0].message


def test_an_undated_image_is_warned_about_not_refused(sentinel2_scene):
    result = validate_inputs(
        [dated(sentinel2_scene, None)],
        InputRequirements(time_range=TimeRange(start=date(2023, 1, 1))),
    )
    assert result.valid
    assert "no acquisition date" in result.warnings[0]


def test_an_area_the_image_does_not_cover_is_refused(sentinel2_scene):
    result = validate_inputs(
        [dated(sentinel2_scene, date(2024, 1, 1))],
        InputRequirements(aoi=AreaOfInterest(bbox=[10.0, 10.0, 10.1, 10.1])),
    )
    assert not result.valid
    assert result.errors[0].code == ErrorCode.SPATIAL_MISMATCH


def test_an_area_the_image_covers_passes(sentinel2_scene):
    west, south, east, north = footprint_lonlat(open_raster(sentinel2_scene))
    result = validate_inputs(
        [dated(sentinel2_scene, date(2024, 1, 1))],
        InputRequirements(aoi=AreaOfInterest(bbox=[west, south, east, north])),
    )
    assert result.valid


def test_a_mixed_pair_and_its_date_gap_are_checked(sentinel2_scene, raster_factory):
    from tests.conftest import make_band

    radar = raster_factory("radar.tif", [make_band("VV", [-10.0] * 4, 2, 2, dtype="float32")], sensor="sentinel1")
    pair = [dated(sentinel2_scene, date(2024, 8, 1)), dated(radar, date(2024, 8, 30))]
    pair[1].id = "image_2"

    result = validate_inputs(pair, InputRequirements(requires_optical_and_sar_pair=True, max_days_between_images=12))
    assert not result.valid
    assert "29 days apart" in result.errors[0].message

    same = validate_inputs([pair[0], pair[0]], InputRequirements(requires_optical_and_sar_pair=True))
    assert "one optical and one SAR" in same.errors[0].message
