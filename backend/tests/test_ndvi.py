"""Tests for the normalised-difference index tools, NDVI foremost.

The expected values here are computed by hand from the band values declared in
``tests/conftest.py``, so a regression in the arithmetic fails the test rather
than quietly shifting the result.
"""

from __future__ import annotations

import math

import pytest

from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.binding import verify_bindings
from app.tools.executor import ToolExecutor, ToolNotImplementedError
from app.tools.indices.ndbi import NDBITool
from app.tools.indices.ndvi import NDVITool
from app.tools.indices.ndwi import NDWITool
from app.tools.raster.io import open_raster
from tests.conftest import SENTINEL2_EXPECTED_NDVI, make_band


@pytest.fixture
def ndvi():
    return NDVITool()


def run(tool, path, tmp_path, **parameters):
    return tool.execute(
        ToolRequest(
            tool_id=tool.tool_id,
            input_references=[path],
            parameters=parameters,
            output_directory=str(tmp_path / "outputs"),
        )
    )


def valid_values(band):
    return [value for value in band if not math.isnan(value)]


# ============================================================
# CORE ARITHMETIC
# ============================================================
def test_ndvi_matches_hand_computed_values(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path)

    result = open_raster(output.artifacts[0].path).band_at(1)

    assert result.to_list() == pytest.approx(SENTINEL2_EXPECTED_NDVI, abs=1e-6)


def test_ndvi_reports_correct_statistics(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path)
    statistics = output.statistics

    assert statistics["valid_pixels"] == 4
    assert statistics["nodata_pixels"] == 0
    assert statistics["total_pixels"] == 4
    assert statistics["valid_fraction"] == 1.0
    assert statistics["minimum"] == pytest.approx(-0.5)
    assert statistics["maximum"] == pytest.approx(0.8)
    assert statistics["mean"] == pytest.approx(0.2)


def test_ndvi_uses_the_documented_formula(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path)

    assert output.data["index"] == "NDVI"
    assert output.data["formula"] == "(B8 - B4) / (B8 + B4)"
    assert output.data["positive_band"] == "B8"
    assert output.data["negative_band"] == "B4"


def test_ndvi_is_invariant_under_a_shared_scale(ndvi, sentinel2_scene, tmp_path):
    # Converting digital numbers to reflectance divides every band by 10000,
    # which cancels in a normalised difference.
    plain = run(ndvi, sentinel2_scene, tmp_path)
    scaled = run(ndvi, sentinel2_scene, tmp_path, scale=1 / 10000)

    assert scaled.statistics["mean"] == pytest.approx(plain.statistics["mean"])
    assert scaled.statistics["minimum"] == pytest.approx(plain.statistics["minimum"])


def test_ndvi_is_shifted_by_an_additive_offset(ndvi, sentinel2_scene, tmp_path):
    # Sentinel-2 baseline 04.00 carries BOA_ADD_OFFSET = -1000; ignoring it
    # changes the index, which is exactly why the parameter exists.
    plain = run(ndvi, sentinel2_scene, tmp_path)
    shifted = run(ndvi, sentinel2_scene, tmp_path, offset=-1000)

    assert shifted.statistics["mean"] != pytest.approx(plain.statistics["mean"])

    # Pixel (0,0): red 1000 -> 0, nir 3000 -> 2000, so NDVI = 2000/2000 = 1.0
    result = open_raster(shifted.artifacts[0].path).band_at(1)
    assert result.sample(0, 0) == pytest.approx(1.0)


def test_ndvi_output_stays_within_index_range(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path)

    for value in open_raster(output.artifacts[0].path).band_at(1):
        assert -1.0 <= value <= 1.0


# ============================================================
# NODATA AND DIVISION BY ZERO
# ============================================================
def test_pixels_where_both_bands_are_zero_become_nodata(ndvi, raster_factory, tmp_path):
    # red + nir == 0 makes the index undefined; it must not become 0.
    red = make_band("B4", [0, 1000], 2, 1)
    nir = make_band("B8", [0, 3000], 2, 1)
    path = raster_factory("zero.tif", [red, nir])

    output = run(ndvi, path, tmp_path)
    result = open_raster(output.artifacts[0].path).band_at(1)

    assert math.isnan(result.sample(0, 0))
    assert result.sample(0, 1) == pytest.approx(0.5)
    assert output.statistics["valid_pixels"] == 1
    assert output.statistics["nodata_pixels"] == 1


def test_nodata_input_pixels_are_excluded(ndvi, raster_factory, tmp_path):
    red = make_band("B4", [1000, 9999], 2, 1, nodata=9999)
    nir = make_band("B8", [3000, 3000], 2, 1, nodata=9999)
    path = raster_factory("masked.tif", [red, nir], nodata=9999)

    output = run(ndvi, path, tmp_path)
    result = open_raster(output.artifacts[0].path).band_at(1)

    assert result.sample(0, 0) == pytest.approx(0.5)
    assert math.isnan(result.sample(0, 1))
    assert output.statistics["valid_pixels"] == 1
    assert output.statistics["valid_fraction"] == pytest.approx(0.5)


def test_statistics_are_none_when_nothing_is_computable(ndvi, raster_factory, tmp_path):
    red = make_band("B4", [0, 0], 2, 1)
    nir = make_band("B8", [0, 0], 2, 1)
    path = raster_factory("allzero.tif", [red, nir])

    output = run(ndvi, path, tmp_path)

    assert output.statistics["valid_pixels"] == 0
    assert output.statistics["mean"] is None
    assert output.statistics["minimum"] is None
    assert output.statistics["valid_fraction"] == 0.0


# ============================================================
# INTERPRETATION
# ============================================================
def test_ndvi_classes_partition_the_valid_pixels(ndvi, sentinel2_scene, tmp_path):
    classes = run(ndvi, sentinel2_scene, tmp_path).data["classes"]

    assert classes["water_or_non_vegetated"]["pixels"] == 1  # -0.50
    assert classes["bare_soil_or_built_up"]["pixels"] == 1   # 0.00
    assert classes["moderate_vegetation"]["pixels"] == 1     # 0.50
    assert classes["dense_vegetation"]["pixels"] == 1        # 0.80
    assert classes["sparse_vegetation"]["pixels"] == 0

    assert sum(entry["pixels"] for entry in classes.values()) == 4
    assert sum(entry["fraction"] for entry in classes.values()) == pytest.approx(1.0)


def test_ndvi_reports_ground_area_when_georeferenced(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path)

    # A 10 m Sentinel-2 pixel covers 100 m2.
    assert output.statistics["pixel_area_square_units"] == pytest.approx(100.0)
    assert output.statistics["valid_area_square_units"] == pytest.approx(400.0)
    assert output.data["classes"]["dense_vegetation"]["area_square_units"] == pytest.approx(100.0)


# ============================================================
# BAND SELECTION
# ============================================================
def test_bands_can_be_named_explicitly(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path, red_band="B4", nir_band="B8")

    assert output.data["positive_band"] == "B8"
    assert output.statistics["mean"] == pytest.approx(0.2)


def test_logical_band_names_from_the_controller_resolve(ndvi, sentinel2_scene, tmp_path):
    # This is exactly what the parameter configurator produces today.
    output = run(ndvi, sentinel2_scene, tmp_path, red_band="red", nir_band="nir")

    assert output.data["positive_band"] == "B8"
    assert output.data["negative_band"] == "B4"


def test_swapping_the_bands_negates_the_index(ndvi, sentinel2_scene, tmp_path):
    normal = run(ndvi, sentinel2_scene, tmp_path)
    swapped = run(ndvi, sentinel2_scene, tmp_path, red_band="B8", nir_band="B4")

    assert swapped.statistics["mean"] == pytest.approx(-normal.statistics["mean"])


def test_identical_bands_are_rejected(ndvi, sentinel2_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="distinct"):
        run(ndvi, sentinel2_scene, tmp_path, red_band="B8", nir_band="B8")


def test_absent_band_is_reported(ndvi, sentinel2_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="B12"):
        run(ndvi, sentinel2_scene, tmp_path, red_band="B12")


def test_non_numeric_scale_is_rejected(ndvi, sentinel2_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="numeric"):
        run(ndvi, sentinel2_scene, tmp_path, scale="wide")


def test_zero_scale_is_rejected(ndvi, sentinel2_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="zero"):
        run(ndvi, sentinel2_scene, tmp_path, scale=0)


# ============================================================
# INPUT HANDLING
# ============================================================
def test_missing_input_is_rejected(ndvi):
    with pytest.raises(ToolExecutionError, match="none was supplied"):
        ndvi.execute(ToolRequest(tool_id="ndvi", input_references=[]))


def test_multiple_inputs_are_rejected(ndvi, sentinel2_scene):
    with pytest.raises(ToolExecutionError, match="single input"):
        ndvi.execute(
            ToolRequest(
                tool_id="ndvi", input_references=[sentinel2_scene, sentinel2_scene]
            )
        )


def test_unreadable_input_is_reported(ndvi, tmp_path):
    with pytest.raises(ToolExecutionError, match="not found"):
        run(ndvi, str(tmp_path / "absent.tif"), tmp_path)


# ============================================================
# ARTIFACTS
# ============================================================
def test_output_raster_keeps_the_source_georeferencing(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path)
    result = open_raster(output.artifacts[0].path)

    assert result.georeference.crs == "EPSG:32643"
    assert result.georeference.pixel_size == (10.0, 10.0)
    assert result.dtype == "float32"
    assert (result.width, result.height) == (2, 2)


def test_artifact_is_described(ndvi, sentinel2_scene, tmp_path):
    artifact = run(ndvi, sentinel2_scene, tmp_path).artifacts[0]

    assert artifact.kind == "raster"
    assert artifact.format == "GTiff"
    assert artifact.path.endswith("_ndvi.tif")
    assert artifact.description


def test_raster_writing_can_be_skipped(ndvi, sentinel2_scene, tmp_path):
    output = run(ndvi, sentinel2_scene, tmp_path, write_raster=False)

    assert output.artifacts == []
    assert output.statistics["mean"] == pytest.approx(0.2)


def test_metadata_records_the_source_and_backend(ndvi, sentinel2_scene, tmp_path):
    metadata = run(ndvi, sentinel2_scene, tmp_path).metadata

    assert metadata["source"]["band_names"] == ["B2", "B3", "B4", "B8"]
    assert metadata["source"]["crs"] == "EPSG:32643"
    assert metadata["sensor"] == "sentinel2"
    assert metadata["raster_backend"] in ("rasterio", "builtin")


# ============================================================
# THE OTHER INDEX TOOLS
# ============================================================
def test_ndwi_uses_green_and_nir(sentinel2_scene, tmp_path):
    output = run(NDWITool(), sentinel2_scene, tmp_path)

    assert output.data["formula"] == "(B3 - B8) / (B3 + B8)"
    # Pixel (0,0): green 1200, nir 3000 -> -1800 / 4200
    result = open_raster(output.artifacts[0].path).band_at(1)
    assert result.sample(0, 0) == pytest.approx(-1800 / 4200)


def test_ndbi_puts_swir_in_the_positive_role(raster_factory, tmp_path):
    nir = make_band("B8", [2000, 1000], 2, 1)
    swir = make_band("B11", [1000, 3000], 2, 1)
    path = raster_factory("builtup.tif", [nir, swir])

    output = run(NDBITool(), path, tmp_path)

    assert output.data["formula"] == "(B11 - B8) / (B11 + B8)"
    result = open_raster(output.artifacts[0].path).band_at(1)
    assert result.sample(0, 0) == pytest.approx(-1000 / 3000)
    assert result.sample(0, 1) == pytest.approx(2000 / 4000)


def test_ndbi_is_the_negation_of_the_reversed_order(raster_factory, tmp_path):
    nir = make_band("B8", [2000, 1000], 2, 1)
    swir = make_band("B11", [1000, 3000], 2, 1)
    path = raster_factory("builtup.tif", [nir, swir])

    ndbi = run(NDBITool(), path, tmp_path)
    reversed_order = run(NDBITool(), path, tmp_path, swir_band="B8", nir_band="B11")

    assert reversed_order.statistics["mean"] == pytest.approx(-ndbi.statistics["mean"])


# ============================================================
# BINDING AND EXECUTOR
# ============================================================
def test_every_binding_matches_a_registered_tool():
    verify_bindings()


def test_executor_runs_a_bound_tool(sentinel2_scene, tmp_path):
    output = ToolExecutor().run(
        "ndvi",
        input_references=[sentinel2_scene],
        output_directory=str(tmp_path / "outputs"),
    )

    assert output.tool_id == "ndvi"
    assert output.result_type == "raster_index"
    assert output.statistics["mean"] == pytest.approx(0.2)


def test_executor_refuses_an_unbound_tool(sentinel2_scene):
    with pytest.raises(ToolNotImplementedError, match="no execution implementation"):
        ToolExecutor().run("satellite_vqa", input_references=[sentinel2_scene])
