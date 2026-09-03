"""Tests for bi-temporal change detection.

The two-date scenes are built so that every expected NDVI, every difference and
every class count can be worked out by hand, which is what makes a regression
in the arithmetic visible rather than merely different.
"""

from __future__ import annotations

import math

import pytest

from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.change.alignment import order_by_acquisition, require_aligned
from app.tools.change.arithmetic import resolve_threshold
from app.tools.change.bitemporal import BiTemporalChangeDetectionTool
from app.tools.raster.io import open_raster
from app.tools.raster.model import GeoReference
from tests.conftest import SENTINEL2_GEOREFERENCE, make_band


@pytest.fixture
def tool():
    return BiTemporalChangeDetectionTool()


def scene(raster_factory, filename, red, nir, date=None, georeference=SENTINEL2_GEOREFERENCE):
    """Write a two-band optical scene, optionally carrying an acquisition date."""
    width = len(red)
    bands = [
        make_band("B4", red, width, 1),
        make_band("B8", nir, width, 1),
    ]
    path = raster_factory(filename, bands, georeference=georeference)
    if date:
        # Stored the way a real product carries it, in the file's own metadata.
        from app.tools.raster.io import write_sidecar

        write_sidecar(
            path,
            {
                "band_names": ["B4", "B8"],
                "sensor": "sentinel2",
                "acquisition_date": date,
            },
        )
    return path


@pytest.fixture
def forest_pair(raster_factory):
    """Four pixels: cleared, regrown, unchanged, unchanged.

    NDVI = (nir - red) / (nir + red)

        pixel  earlier                  later                    dNDVI
        0      1000/4000 ->  0.60       3000/1000 -> -0.50       -1.10  cleared
        1      3000/1000 -> -0.50       1000/4000 ->  0.60       +1.10  regrown
        2      1000/3000 ->  0.50       1000/3000 ->  0.50        0.00  stable
        3      2000/2000 ->  0.00       2000/2000 ->  0.00        0.00  stable
    """
    earlier = scene(
        raster_factory, "earlier.tif",
        red=[1000, 3000, 1000, 2000], nir=[4000, 1000, 3000, 2000],
        date="2024-01-15",
    )
    later = scene(
        raster_factory, "later.tif",
        red=[3000, 1000, 1000, 2000], nir=[1000, 4000, 3000, 2000],
        date="2026-01-15",
    )
    return earlier, later


def run(tool, paths, tmp_path, **parameters):
    return tool.execute(
        ToolRequest(
            tool_id=tool.tool_id,
            input_references=list(paths),
            parameters=parameters,
            output_directory=str(tmp_path / "outputs"),
        )
    )


# ============================================================
# CORE ARITHMETIC
# ============================================================
def test_change_matches_hand_computed_differences(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path)

    difference = open_raster(output.artifacts[0].path).band_at(1)
    assert difference.to_list() == pytest.approx([-1.1, 1.1, 0.0, 0.0], abs=1e-6)


def test_classes_are_counted_correctly(tool, forest_pair, tmp_path):
    classes = run(tool, forest_pair, tmp_path).data["classes"]

    assert classes["decrease"]["pixels"] == 1
    assert classes["increase"]["pixels"] == 1
    assert classes["stable"]["pixels"] == 2
    assert sum(entry["pixels"] for entry in classes.values()) == 4


def test_statistics_describe_the_change(tool, forest_pair, tmp_path):
    statistics = run(tool, forest_pair, tmp_path).statistics

    assert statistics["valid_pixels"] == 4
    assert statistics["total_pixels"] == 4
    assert statistics["changed_pixels"] == 2
    assert statistics["changed_fraction"] == pytest.approx(0.5)
    assert statistics["minimum"] == pytest.approx(-1.1)
    assert statistics["maximum"] == pytest.approx(1.1)
    assert statistics["mean"] == pytest.approx(0.0)


def test_classification_raster_uses_the_documented_codes(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path)

    codes = open_raster(output.artifacts[1].path).band_at(1)
    # 1 = decrease, 3 = increase, 2 = stable
    assert codes.to_list() == [1, 3, 2, 2]


def test_areas_are_reported_for_a_projected_crs(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path)

    # 10 m pixels, so each is 100 m2.
    assert output.statistics["pixel_area_square_units"] == pytest.approx(100.0)
    assert output.data["classes"]["decrease"]["area_square_units"] == pytest.approx(100.0)


# ============================================================
# TEMPORAL ORDER
# ============================================================
def test_order_comes_from_acquisition_dates_not_input_order(tool, forest_pair, tmp_path):
    earlier, later = forest_pair

    forward = run(tool, (earlier, later), tmp_path)
    reversed_upload = run(tool, (later, earlier), tmp_path)

    assert forward.data["temporal_order_source"] == "acquisition_date"
    assert forward.data["earlier_date"] == "2024-01-15"
    assert forward.data["later_date"] == "2026-01-15"

    # Uploading the pair the other way round must not invert the result.
    assert reversed_upload.statistics["minimum"] == pytest.approx(
        forward.statistics["minimum"]
    )
    assert reversed_upload.data["classes"] == forward.data["classes"]


def test_undated_images_fall_back_to_input_order_and_say_so(
    tool, raster_factory, tmp_path
):
    earlier = scene(
        raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000]
    )
    later = scene(
        raster_factory, "b.tif", red=[3000, 2000], nir=[1000, 2000]
    )

    output = run(tool, (earlier, later), tmp_path)

    assert output.data["temporal_order_source"] == "input_order"
    assert "assumed" in output.data["note"]
    # NDVI falls 0.60 -> -0.50 on the first pixel.
    difference = open_raster(output.artifacts[0].path).band_at(1)
    assert difference.sample(0, 0) == pytest.approx(-1.1)


def test_identical_dates_are_rejected(tool, raster_factory, tmp_path):
    earlier = scene(
        raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000], date="2025-06-01"
    )
    later = scene(
        raster_factory, "b.tif", red=[3000, 2000], nir=[1000, 2000], date="2025-06-01"
    )

    with pytest.raises(ToolExecutionError, match="same acquisition date"):
        run(tool, (earlier, later), tmp_path)


# ============================================================
# ALIGNMENT IS PROVEN, NOT ASSUMED
# ============================================================
def test_differently_sized_images_are_refused(tool, raster_factory, tmp_path):
    earlier = scene(raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000])
    later = scene(
        raster_factory, "b.tif", red=[1000, 2000, 3000], nir=[4000, 2000, 1000]
    )

    with pytest.raises(ToolExecutionError, match="different dimensions"):
        run(tool, (earlier, later), tmp_path)


def test_different_crs_is_refused(tool, raster_factory, tmp_path):
    earlier = scene(raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000])
    later = scene(
        raster_factory, "b.tif", red=[1000, 2000], nir=[4000, 2000],
        georeference=GeoReference(
            crs="EPSG:32644", transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0)
        ),
    )

    with pytest.raises(ToolExecutionError, match="different coordinate reference"):
        run(tool, (earlier, later), tmp_path)


def test_different_resolution_is_refused(tool, raster_factory, tmp_path):
    earlier = scene(raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000])
    later = scene(
        raster_factory, "b.tif", red=[1000, 2000], nir=[4000, 2000],
        georeference=GeoReference(
            crs="EPSG:32643", transform=(699960.0, 20.0, 0.0, 2100000.0, 0.0, -20.0)
        ),
    )

    with pytest.raises(ToolExecutionError, match="different pixel"):
        run(tool, (earlier, later), tmp_path)


def test_offset_grids_are_refused(tool, raster_factory, tmp_path):
    earlier = scene(raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000])
    later = scene(
        raster_factory, "b.tif", red=[1000, 2000], nir=[4000, 2000],
        georeference=GeoReference(
            # Shifted east by 5 pixels: same size, same CRS, wrong ground.
            crs="EPSG:32643", transform=(700010.0, 10.0, 0.0, 2100000.0, 0.0, -10.0)
        ),
    )

    with pytest.raises(ToolExecutionError, match="offset by"):
        run(tool, (earlier, later), tmp_path)


def test_sub_pixel_offset_is_tolerated(raster_factory):
    # Real products are rarely bit-identical in their transforms.
    first = open_raster(
        scene(raster_factory, "a.tif", red=[1000, 2000], nir=[4000, 2000])
    )
    second = open_raster(
        scene(
            raster_factory, "b.tif", red=[1000, 2000], nir=[4000, 2000],
            georeference=GeoReference(
                crs="EPSG:32643",
                transform=(699960.001, 10.0, 0.0, 2100000.0, 0.0, -10.0),
            ),
        )
    )

    require_aligned(first, second)  # must not raise


# ============================================================
# NODATA
# ============================================================
def test_a_pixel_invalid_on_one_date_is_nodata(tool, raster_factory, tmp_path):
    # Pixel 1 has red + nir == 0 on the later date, so NDVI is undefined there
    # and no change value may be asserted for it.
    earlier = scene(raster_factory, "a.tif", red=[1000, 1000], nir=[3000, 3000])
    later = scene(raster_factory, "b.tif", red=[1000, 0], nir=[3000, 0])

    output = run(tool, (earlier, later), tmp_path)

    difference = open_raster(output.artifacts[0].path).band_at(1)
    assert difference.sample(0, 0) == pytest.approx(0.0)
    assert math.isnan(difference.sample(0, 1))

    assert output.statistics["valid_pixels"] == 1
    assert output.statistics["nodata_pixels"] == 1
    assert output.statistics["valid_fraction"] == pytest.approx(0.5)


def test_nothing_comparable_is_reported_honestly(tool, raster_factory, tmp_path):
    earlier = scene(raster_factory, "a.tif", red=[0, 0], nir=[0, 0])
    later = scene(raster_factory, "b.tif", red=[0, 0], nir=[0, 0])

    output = run(tool, (earlier, later), tmp_path, threshold=0.2)

    assert output.statistics["valid_pixels"] == 0
    assert output.statistics["mean"] is None
    assert output.statistics["changed_fraction"] == 0.0


# ============================================================
# THRESHOLDING
# ============================================================
def test_threshold_controls_what_counts_as_change(tool, forest_pair, tmp_path):
    strict = run(tool, forest_pair, tmp_path, threshold=1.5)
    loose = run(tool, forest_pair, tmp_path, threshold=0.05)

    assert strict.statistics["changed_pixels"] == 0
    assert loose.statistics["changed_pixels"] == 2


def test_statistical_threshold_adapts_to_the_scene(tool, forest_pair, tmp_path):
    output = run(
        tool, forest_pair, tmp_path,
        threshold_method="statistical", sigma_multiplier=1.0,
    )

    # Differences are [-1.1, 1.1, 0, 0]; mean 0, so sigma = sqrt(2.42/4) ~ 0.778.
    assert output.data["threshold"] == pytest.approx(0.7778, abs=1e-3)
    assert "standard deviations" in output.data["threshold_description"]
    assert output.statistics["changed_pixels"] == 2


def test_statistical_threshold_needs_variation(tool, raster_factory, tmp_path):
    earlier = scene(raster_factory, "a.tif", red=[1000, 1000], nir=[3000, 3000])
    later = scene(raster_factory, "b.tif", red=[1000, 1000], nir=[3000, 3000])

    with pytest.raises(ToolExecutionError, match="no variation"):
        run(tool, (earlier, later), tmp_path, threshold_method="statistical")


def test_unknown_threshold_method_is_rejected(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="Unknown threshold_method"):
        run(tool, forest_pair, tmp_path, threshold_method="magic")


def test_negative_threshold_is_rejected(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="must be positive"):
        run(tool, forest_pair, tmp_path, threshold=-0.5)


def test_threshold_resolution_is_unit_testable():
    threshold, description = resolve_threshold(
        {"standard_deviation": 0.25}, "statistical", 0.2, 2.0
    )
    assert threshold == pytest.approx(0.5)
    assert "2 standard deviations" in description

    threshold, description = resolve_threshold({}, "fixed", 0.3, 2.0)
    assert threshold == pytest.approx(0.3)
    assert "fixed threshold" in description


# ============================================================
# INDEX SELECTION
# ============================================================
def test_the_differenced_index_can_be_chosen(tool, raster_factory, tmp_path):
    # NDWI needs green, so the scene must actually carry it.
    def water_scene(name, green, nir):
        bands = [
            make_band("B3", green, 2, 1),
            make_band("B8", nir, 2, 1),
        ]
        return raster_factory(name, bands)

    earlier = water_scene("dry.tif", green=[1000, 1000], nir=[3000, 3000])
    later = water_scene("flooded.tif", green=[3000, 1000], nir=[1000, 3000])

    output = run(tool, (earlier, later), tmp_path, index="ndwi")

    assert output.data["index"] == "NDWI"
    assert output.data["formula"] == "dNDWI = NDWI(later) - NDWI(earlier)"
    assert output.data["index_formula"] == "(B3 - B8) / (B3 + B8)"
    assert output.data["increase_means"] == "water extent gain"

    # Pixel 0 flooded: NDWI -0.5 -> +0.5, so dNDWI = +1.0
    difference = open_raster(output.artifacts[0].path).band_at(1)
    assert difference.sample(0, 0) == pytest.approx(1.0)
    assert output.data["classes"]["increase"]["pixels"] == 1


def test_ndwi_on_a_scene_without_green_is_refused(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="green"):
        run(tool, forest_pair, tmp_path, index="ndwi")


def test_default_index_is_ndvi(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path)

    assert output.data["index"] == "NDVI"
    assert output.data["increase_means"] == "vegetation gain"
    assert output.data["decrease_means"] == "vegetation loss"


def test_unknown_index_is_rejected(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="Unknown index"):
        run(tool, forest_pair, tmp_path, index="ndxi")


def test_bands_can_be_named_explicitly(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path, red_band="B4", nir_band="B8")

    assert output.data["index_formula"] == "(B8 - B4) / (B8 + B4)"


# ============================================================
# INPUT HANDLING
# ============================================================
def test_a_single_image_is_rejected(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="exactly two"):
        run(tool, forest_pair[:1], tmp_path)


def test_three_images_are_rejected(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="exactly two"):
        run(tool, (*forest_pair, forest_pair[0]), tmp_path)


def test_unreadable_input_is_reported(tool, forest_pair, tmp_path):
    with pytest.raises(ToolExecutionError, match="not found"):
        run(tool, (forest_pair[0], str(tmp_path / "absent.tif")), tmp_path)


def test_raster_writing_can_be_skipped(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path, write_raster=False)

    assert output.artifacts == []
    assert output.statistics["changed_pixels"] == 2


def test_output_rasters_keep_the_source_georeferencing(tool, forest_pair, tmp_path):
    output = run(tool, forest_pair, tmp_path)

    for artifact in output.artifacts:
        result = open_raster(artifact.path)
        assert result.georeference.crs == "EPSG:32643"
        assert result.georeference.pixel_size == (10.0, 10.0)


def test_alignment_helper_is_unit_testable(raster_factory):
    first = open_raster(scene(raster_factory, "a.tif", red=[1, 2], nir=[3, 4]))
    second = open_raster(scene(raster_factory, "b.tif", red=[1, 2], nir=[3, 4]))

    require_aligned(first, second)
    earlier, later, ordering = order_by_acquisition(first, second)

    assert ordering["temporal_order_source"] == "input_order"
    assert earlier is first and later is second
