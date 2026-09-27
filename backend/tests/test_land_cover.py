"""Tests for rule-based land-cover classification.

The scene is six pixels, one per class plus one nodata pixel, with digital
numbers chosen so every index can be checked by hand::

    pixel  B3    B4    B8    B11   NDWI    NDVI    NDBI    class
    0      1000   600   200   100  +0.667  -0.500  -0.333  water
    1       800   500  4000  1500  -0.667  +0.778  -0.455  dense_vegetation
    2      1000  1000  2000  1500  -0.333  +0.333  -0.143  sparse_vegetation
    3      1400  1600  1900  2400  -0.152  +0.086  +0.116  built_up
    4      1300  1700  2000  1800  -0.212  +0.081  -0.053  bare_soil
    5         0     0     0     0  (nodata)
"""

from __future__ import annotations

import pytest

from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.landcover import classifier
from app.tools.landcover.classifier import Thresholds, classify_land_cover, rule
from app.tools.landcover.tool import LandCoverClassificationTool
from app.tools.raster.io import open_raster
from tests.conftest import make_band

GREEN = [1000, 800, 1000, 1400, 1300, 0]
RED = [600, 500, 1000, 1600, 1700, 0]
NIR = [200, 4000, 2000, 1900, 2000, 0]
SWIR = [100, 1500, 1500, 2400, 1800, 0]


@pytest.fixture
def scene(raster_factory):
    bands = [
        make_band("B3", GREEN, 3, 2, nodata=0),
        make_band("B4", RED, 3, 2, nodata=0),
        make_band("B8", NIR, 3, 2, nodata=0),
        make_band("B11", SWIR, 3, 2, nodata=0),
    ]
    return raster_factory("land_cover.tif", bands, nodata=0)


@pytest.fixture
def scene_without_swir(raster_factory):
    bands = [
        make_band("B3", GREEN, 3, 2, nodata=0),
        make_band("B4", RED, 3, 2, nodata=0),
        make_band("B8", NIR, 3, 2, nodata=0),
    ]
    return raster_factory("land_cover_no_swir.tif", bands, nodata=0)


def run(path, tmp_path, **parameters):
    return LandCoverClassificationTool().execute(
        ToolRequest(
            tool_id="land_cover_classification",
            input_references=[path],
            parameters=parameters,
            output_directory=str(tmp_path / "out"),
        )
    )


def test_every_pixel_lands_in_the_hand_computed_class(scene, tmp_path):
    output = run(scene, tmp_path)

    classes = output.data["classes"]
    assert {label: entry["pixels"] for label, entry in classes.items()} == {
        "water": 1,
        "dense_vegetation": 1,
        "sparse_vegetation": 1,
        "built_up": 1,
        "bare_soil": 1,
    }
    assert output.statistics["valid_pixels"] == 5
    assert output.statistics["nodata_pixels"] == 1
    assert output.data["swir_available"] is True


def test_the_class_raster_holds_the_class_codes(scene, tmp_path):
    output = run(scene, tmp_path)

    raster = open_raster(output.artifacts[0].path)
    assert [int(value) for value in raster.bands[0].values] == [1, 2, 3, 4, 5, 0]
    assert raster.georeference.crs == "EPSG:32643"
    assert output.data["class_codes"]["4"] == "built_up"


def test_without_swir_bare_and_built_up_are_merged_not_guessed(scene_without_swir, tmp_path):
    output = run(scene_without_swir, tmp_path)

    classes = output.data["classes"]
    assert set(classes) == {
        "water", "dense_vegetation", "sparse_vegetation", "bare_or_built_up",
    }
    assert classes["bare_or_built_up"]["pixels"] == 2
    assert output.data["swir_available"] is False
    assert "cannot be told apart" in output.data["interpretation"]


def test_areas_are_reported_in_ground_units(scene, tmp_path):
    output = run(scene, tmp_path)
    # 10 m pixels: 100 m2 each.
    assert output.data["classes"]["water"]["area_square_units"] == pytest.approx(100.0)
    assert output.statistics["valid_area_square_units"] == pytest.approx(500.0)


def test_thresholds_are_parameters_and_are_reported(scene, tmp_path):
    # Raising the dense threshold above pixel 1's NDVI of 0.778 demotes it.
    output = run(scene, tmp_path, dense_vegetation_threshold=0.8)

    assert output.data["classes"]["dense_vegetation"]["pixels"] == 0
    assert output.data["classes"]["sparse_vegetation"]["pixels"] == 2
    assert "dense_vegetation: NDVI >= 0.8" in output.data["rules"]


def test_inconsistent_thresholds_are_refused_before_any_work():
    tool = LandCoverClassificationTool()
    with pytest.raises(ToolExecutionError, match="below the dense-vegetation"):
        tool.preflight(
            ToolRequest(
                tool_id="land_cover_classification",
                parameters={"vegetation_threshold": 0.6, "dense_vegetation_threshold": 0.5},
            )
        )
    with pytest.raises(ToolExecutionError, match="must lie in"):
        Thresholds(water=3.0).validate()


def test_the_rules_apply_in_order():
    thresholds = Thresholds()
    # Water wins even over a high NDVI: NDWI is checked first.
    assert rule(ndvi=0.9, ndwi=0.1, ndbi=None, t=thresholds) == classifier.WATER
    assert rule(ndvi=0.1, ndwi=-0.2, ndbi=0.2, t=thresholds) == classifier.BUILT_UP
    assert rule(ndvi=0.1, ndwi=-0.2, ndbi=-0.2, t=thresholds) == classifier.BARE_SOIL
    assert rule(ndvi=0.1, ndwi=-0.2, ndbi=None, t=thresholds) == classifier.BARE_OR_BUILT_UP


def test_the_pure_python_path_gives_identical_codes(scene, monkeypatch):
    dataset = open_raster(scene)
    bands = [dataset.band(name) for name in ("B3", "B4", "B8", "B11")]

    fast = classify_land_cover(*bands, Thresholds())
    monkeypatch.setattr(classifier, "has_numpy", lambda: False)
    slow = classify_land_cover(*bands, Thresholds())

    assert [int(v) for v in fast.band.values] == [int(v) for v in slow.band.values]
    assert fast.counts == slow.counts


def test_bands_on_different_grids_are_refused():
    small = make_band("a", [1, 2], 2, 1)
    large = make_band("b", [1, 2, 3, 4], 2, 2)
    with pytest.raises(ToolExecutionError, match="same grid"):
        classify_land_cover(small, large, large, None, Thresholds())
