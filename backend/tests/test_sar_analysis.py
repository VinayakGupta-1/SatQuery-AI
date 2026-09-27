"""Tests for SAR water mapping and the backscatter arithmetic beneath it."""

from __future__ import annotations

import math

import pytest

from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.raster.io import open_raster
from app.tools.sar import backscatter
from app.tools.sar.backscatter import (
    boxcar,
    detect_units,
    otsu_threshold,
    resolve_polarisation,
    to_decibels,
    to_linear_power,
)
from app.tools.sar.tool import SARAnalysisTool
from tests.conftest import make_band

#: Six VV values in dB: three below -18 dB (water), three above.
VV_DB = [-25.0, -20.0, -10.0, -5.0, -19.0, -12.0]


@pytest.fixture
def sar_db(raster_factory):
    return raster_factory(
        "sar_db.tif", [make_band("VV", VV_DB, 3, 2, dtype="float32")], sensor="sentinel1"
    )


@pytest.fixture
def sar_linear(raster_factory):
    linear = [10 ** (value / 10) for value in VV_DB]
    return raster_factory(
        "sar_linear.tif", [make_band("VV", linear, 3, 2, dtype="float32")], sensor="sentinel1"
    )


def run(path, tmp_path, **parameters):
    return SARAnalysisTool().execute(
        ToolRequest(
            tool_id="sar_analysis",
            input_references=[path],
            parameters=parameters,
            output_directory=str(tmp_path / "out"),
        )
    )


def test_water_is_backscatter_below_the_threshold(sar_db, tmp_path):
    output = run(sar_db, tmp_path, speckle_filter="none")

    assert output.data["input_units"] == "db"
    assert output.data["threshold"] == -18.0
    assert output.data["classes"]["water"]["pixels"] == 3
    assert output.data["classes"]["non_water"]["pixels"] == 3
    assert output.statistics["water_fraction"] == pytest.approx(0.5)

    water_map = open_raster(output.artifacts[0].path).bands[0]
    assert [int(v) for v in water_map.values] == [1, 1, 2, 2, 1, 2]


def test_linear_power_is_detected_and_gives_the_same_map(sar_db, sar_linear, tmp_path):
    from_db = run(sar_db, tmp_path, speckle_filter="none")
    from_linear = run(sar_linear, tmp_path, speckle_filter="none")

    assert from_linear.data["input_units"] == "linear"
    assert from_linear.data["classes"] == from_db.data["classes"]
    assert from_linear.statistics["median"] == pytest.approx(from_db.statistics["median"], abs=1e-4)


def test_uncalibrated_digital_numbers_are_refused(raster_factory, tmp_path):
    path = raster_factory(
        "sar_dn.tif", [make_band("VV", [120, 340, 560, 780], 2, 2)], sensor="sentinel1"
    )
    with pytest.raises(ToolExecutionError, match="uncalibrated digital numbers"):
        run(path, tmp_path)


def test_a_stated_unit_overrides_detection(sar_db, tmp_path):
    # Reading dB values as linear power makes every negative value invalid.
    output = run(sar_db, tmp_path, speckle_filter="none", input_units="linear")
    assert output.data["input_units_source"] == "parameter"
    assert output.statistics["valid_pixels"] == 0


def test_otsu_splits_a_bimodal_scene_between_its_modes(raster_factory, tmp_path):
    values = [-22.0] * 50 + [-8.0] * 50
    path = raster_factory(
        "bimodal.tif", [make_band("VV", values, 10, 10, dtype="float32")], sensor="sentinel1"
    )
    output = run(path, tmp_path, speckle_filter="none", threshold_method="otsu")

    assert -22.0 < output.data["threshold"] < -8.0
    assert output.data["classes"]["water"]["pixels"] == 50


def test_the_boxcar_averages_linear_power_over_valid_neighbours():
    power = [1.0] * 9
    power[4] = 10.0
    valid = [True] * 9

    smoothed = boxcar(power, valid, 3, 3, 3)
    assert smoothed[4] == pytest.approx(18.0 / 9)
    # A corner sees itself, two edges and the centre.
    assert smoothed[0] == pytest.approx(13.0 / 4)


def test_the_boxcar_skips_nodata_rather_than_counting_it_as_zero():
    power = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    valid = [True, True, True, True, True, True, True, True, False]
    smoothed = boxcar(power, valid, 3, 3, 3)
    assert smoothed[4] == pytest.approx(1.0)
    assert math.isnan(float(smoothed[8]))


def test_both_backends_agree(sar_db, monkeypatch):
    band = open_raster(sar_db).bands[0]
    fast_power, fast_valid = to_linear_power(band, "db")
    fast = [float(v) for v in to_decibels(boxcar(fast_power, fast_valid, 3, 2, 3), fast_valid)]
    fast_units = detect_units(band)
    fast_otsu = otsu_threshold(fast, fast_valid)

    monkeypatch.setattr(backscatter, "has_numpy", lambda: False)
    slow_power, slow_valid = to_linear_power(band, "db")
    slow = to_decibels(boxcar(slow_power, slow_valid, 3, 2, 3), slow_valid)

    assert fast == pytest.approx(slow, abs=1e-9)
    assert fast_units == detect_units(band) == "db"
    assert fast_otsu == pytest.approx(otsu_threshold(slow, slow_valid))


def test_the_polarisation_is_chosen_and_can_be_named(raster_factory, tmp_path):
    path = raster_factory(
        "dual.tif",
        [
            make_band("VH", [-30.0, -15.0], 2, 1, dtype="float32"),
            make_band("VV", [-25.0, -5.0], 2, 1, dtype="float32"),
        ],
        sensor="sentinel1",
    )
    dataset = open_raster(path)
    assert resolve_polarisation(dataset, None).name == "VV"  # co-pol preferred
    assert resolve_polarisation(dataset, "vh").name == "VH"

    output = run(path, tmp_path, speckle_filter="none", polarisation="VH")
    assert output.data["polarisation"] == "VH"
    assert output.data["threshold"] == -24.0  # the cross-pol default

    with pytest.raises(ToolExecutionError, match="not present"):
        resolve_polarisation(dataset, "HH")


def test_an_optical_raster_has_no_polarisation_to_map(sentinel2_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="No SAR polarisation band"):
        run(sentinel2_scene, tmp_path)


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({"threshold_method": "magic"}, "Unknown threshold_method"),
        ({"speckle_filter": "lee"}, "Unknown speckle_filter"),
        ({"filter_window": 4}, "odd integer"),
    ],
)
def test_bad_parameters_are_refused_clearly(sar_db, tmp_path, parameters, message):
    with pytest.raises(ToolExecutionError, match=message):
        run(sar_db, tmp_path, **parameters)
