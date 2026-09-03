"""Tests for multi-file scenes, resampling, and cloud masking.

Together these are what let a real satellite product be analysed: products
arrive as one file per band, at several resolutions, with a cloud mask that
must be honoured before any statistic means anything.
"""

from __future__ import annotations

import math
import os

import pytest

from app.tools.base import ToolExecutionError, ToolRequest
from app.tools.executor import ToolExecutor
from app.tools.indices.ndvi import NDVITool
from app.tools.raster.bands import canonical_name
from app.tools.raster.io import open_raster, write_raster
from app.tools.raster.masking import (
    DEFAULT_SCL_INVALID,
    build_validity_mask,
    parse_mask_values,
)
from app.tools.raster.model import GeoReference, RasterError
from app.tools.raster.resample import resample_band
from app.tools.raster.scene import (
    band_name_from_filename,
    discover_scene_bands,
    write_scene_manifest,
)
from tests.conftest import make_band

# A 10 m grid and the 20 m grid covering exactly the same ground.
GRID_10M = GeoReference(crs="EPSG:32643", transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0))
GRID_20M = GeoReference(crs="EPSG:32643", transform=(699960.0, 20.0, 0.0, 2100000.0, 0.0, -20.0))


def band_file(tmp_path, name, values, width, height, grid, dtype="uint16"):
    """Write one single-band raster, the way a real product ships them."""
    path = str(tmp_path / name)
    write_raster(
        path,
        [make_band(name.split(".")[0], values, width, height, dtype=dtype)],
        grid,
        dtype=dtype,
        metadata={"sensor": "sentinel2"},
    )
    return path


# ============================================================
# ZERO-PADDED BAND NAMES
# ============================================================
def test_real_sentinel2_band_names_resolve():
    # Products name their files B01..B12, not B1..B12. Every real scene
    # depends on this mapping.
    assert canonical_name("B04", "sentinel2") == "red"
    assert canonical_name("B08", "sentinel2") == "nir"
    assert canonical_name("B03", "sentinel2") == "green"
    assert canonical_name("B11", "sentinel2") == "swir1"
    assert canonical_name("B08A", "sentinel2") == "narrow_nir"
    assert canonical_name("SR_B5", "landsat8") == "nir"


def test_unpadded_names_still_resolve():
    assert canonical_name("B4", "sentinel2") == "red"
    assert canonical_name("B8", "sentinel2") == "nir"


# ============================================================
# RESAMPLING
# ============================================================
def test_coarse_band_is_upsampled_onto_the_fine_grid(tmp_path):
    # A 2x2 band at 20 m covers the same ground as 4x4 at 10 m, so each
    # source pixel must appear in a 2x2 block of the result.
    coarse = make_band("B11", [1, 2, 3, 4], 2, 2)

    result = resample_band(coarse, GRID_20M, GRID_10M, 4, 4)

    assert (result.width, result.height) == (4, 4)
    assert result.to_list() == [
        1, 1, 2, 2,
        1, 1, 2, 2,
        3, 3, 4, 4,
        3, 3, 4, 4,
    ]


def test_upsampling_replicates_rather_than_interpolates(tmp_path):
    coarse = make_band("B11", [10, 20, 30, 40], 2, 2)

    result = resample_band(coarse, GRID_20M, GRID_10M, 4, 4)

    # Every output value is one the sensor actually recorded; nothing
    # intermediate has been invented.
    assert set(result.to_list()) == {10, 20, 30, 40}


def test_resampling_respects_the_geotransform_not_array_shape():
    # Same pixel size, but the source sits one pixel east. A naive index-based
    # resample would ignore that and return the wrong ground.
    shifted = GeoReference(
        crs="EPSG:32643", transform=(699970.0, 10.0, 0.0, 2100000.0, 0.0, -10.0)
    )
    band = make_band("B4", [1, 2, 3, 4], 4, 1)

    result = resample_band(band, shifted, GRID_10M, 4, 1, nodata=0)

    # Target column 0 lies west of the source, so it has no data; the rest
    # shift across by one.
    assert result.to_list() == [0, 1, 2, 3]


def test_pixels_outside_the_source_become_nodata():
    band = make_band("B4", [5, 6], 2, 1)
    wider = GeoReference(
        crs="EPSG:32643", transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0)
    )

    result = resample_band(band, wider, wider, 4, 1, nodata=0)

    assert result.to_list() == [5, 6, 0, 0]


def test_rotated_rasters_are_refused():
    rotated = GeoReference(
        crs="EPSG:32643", transform=(699960.0, 10.0, 0.5, 2100000.0, 0.5, -10.0)
    )
    band = make_band("B4", [1, 2, 3, 4], 2, 2)

    with pytest.raises(RasterError, match="north-up"):
        resample_band(band, rotated, GRID_10M, 2, 2)


def test_unknown_resampling_method_is_refused():
    band = make_band("B4", [1, 2, 3, 4], 2, 2)

    with pytest.raises(RasterError, match="Unsupported resampling"):
        resample_band(band, GRID_10M, GRID_10M, 2, 2, method="bicubic")


# ============================================================
# MULTI-FILE SCENES
# ============================================================
def test_a_manifest_assembles_bands_into_one_dataset(tmp_path):
    red = band_file(tmp_path, "B04.tif", [1000, 2000, 3000, 500], 2, 2, GRID_10M)
    nir = band_file(tmp_path, "B08.tif", [3000, 2000, 1000, 4500], 2, 2, GRID_10M)

    manifest = str(tmp_path / "scene.satquery-scene.json")
    write_scene_manifest(
        manifest,
        bands=[{"name": "B04", "path": red}, {"name": "B08", "path": nir}],
        metadata={"sensor": "sentinel2", "acquisition_date": "2025-03-11"},
    )

    dataset = open_raster(manifest)

    assert dataset.band_names == ["B04", "B08"]
    assert (dataset.width, dataset.height) == (2, 2)
    assert dataset.band("B04").to_list() == [1000, 2000, 3000, 500]
    assert dataset.metadata["sensor"] == "sentinel2"


def test_a_scene_mixing_resolutions_is_resampled_to_the_finest(tmp_path):
    # This is exactly the Sentinel-2 NDBI case: NIR at 10 m, SWIR at 20 m.
    nir = band_file(tmp_path, "B08.tif", [1000] * 16, 4, 4, GRID_10M)
    swir = band_file(tmp_path, "B11.tif", [3000, 3000, 3000, 3000], 2, 2, GRID_20M)

    manifest = str(tmp_path / "s2.satquery-scene.json")
    write_scene_manifest(
        manifest,
        bands=[{"name": "B08", "path": nir}, {"name": "B11", "path": swir}],
        metadata={"sensor": "sentinel2"},
    )

    dataset = open_raster(manifest)

    # The 10 m band defines the grid; the 20 m band was lifted onto it.
    assert (dataset.width, dataset.height) == (4, 4)
    assert dataset.georeference.pixel_size == (10.0, 10.0)
    assert dataset.metadata["scene_reference_band"] == "B08"
    assert dataset.metadata["resampled_bands"] == ["B11"]
    assert len(dataset.band("B11").to_list()) == 16


def test_ndbi_now_works_across_resolutions(tmp_path):
    # Before resampling existed, NDBI could not be computed on native
    # Sentinel-2 data at all, because B08 and B11 never shared a grid.
    nir = band_file(tmp_path, "B08.tif", [1000] * 16, 4, 4, GRID_10M)
    swir = band_file(tmp_path, "B11.tif", [3000] * 4, 2, 2, GRID_20M)

    manifest = str(tmp_path / "urban.satquery-scene.json")
    write_scene_manifest(
        manifest,
        bands=[{"name": "B08", "path": nir}, {"name": "B11", "path": swir}],
        metadata={"sensor": "sentinel2"},
    )

    output = ToolExecutor().run(
        "ndbi", input_references=[manifest], output_directory=str(tmp_path / "out")
    )

    # (3000 - 1000) / (3000 + 1000) = 0.5 everywhere.
    assert output.statistics["mean"] == pytest.approx(0.5)
    assert output.statistics["valid_pixels"] == 16
    assert output.data["formula"] == "(B11 - B08) / (B11 + B08)"


def test_bands_in_different_crs_are_refused(tmp_path):
    a = band_file(tmp_path, "B04.tif", [1, 2, 3, 4], 2, 2, GRID_10M)
    b = band_file(
        tmp_path, "B08.tif", [1, 2, 3, 4], 2, 2,
        GeoReference(crs="EPSG:32644", transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0)),
    )

    manifest = str(tmp_path / "mixed.satquery-scene.json")
    write_scene_manifest(
        manifest, bands=[{"name": "B04", "path": a}, {"name": "B08", "path": b}]
    )

    with pytest.raises(RasterError, match="different coordinate reference"):
        open_raster(manifest)


def test_a_manifest_naming_a_missing_file_is_refused(tmp_path):
    manifest = str(tmp_path / "broken.satquery-scene.json")
    write_scene_manifest(manifest, bands=[{"name": "B04", "path": "absent.tif"}])

    with pytest.raises(RasterError, match="does not exist"):
        open_raster(manifest)


def test_an_empty_manifest_is_refused(tmp_path):
    with pytest.raises(RasterError, match="at least one band"):
        write_scene_manifest(str(tmp_path / "empty.satquery-scene.json"), bands=[])


def test_a_non_manifest_json_is_refused(tmp_path):
    path = tmp_path / "other.satquery-scene.json"
    path.write_text('{"type": "something_else"}', encoding="utf-8")

    with pytest.raises(RasterError, match="not a SatQuery scene manifest"):
        open_raster(str(path))


# ============================================================
# PRODUCT DIRECTORIES
# ============================================================
def test_band_names_are_read_from_product_filenames():
    assert band_name_from_filename("T43RGM_20250311T053649_B04_10m.jp2") == "B04"
    assert band_name_from_filename("T43RGM_20250311T053649_B8A_20m.jp2") == "B8A"
    assert band_name_from_filename("LC09_L2SP_147039_20250311_SR_B5.TIF") == "B5"
    assert band_name_from_filename("readme.txt") is None
    assert band_name_from_filename("T43RGM_20250311T053649_TCI_10m.jp2") is None


def test_a_product_directory_is_opened_as_one_scene(tmp_path):
    # Mimic a SAFE layout: imagery nested under resolution folders.
    granule = tmp_path / "GRANULE" / "L2A_T43RGM" / "IMG_DATA" / "R10m"
    granule.mkdir(parents=True)
    band_file(granule, "T43RGM_20250311_B04_10m.tif", [1000, 2000, 3000, 500], 2, 2, GRID_10M)
    band_file(granule, "T43RGM_20250311_B08_10m.tif", [3000, 2000, 1000, 4500], 2, 2, GRID_10M)

    dataset = open_raster(str(tmp_path))

    assert sorted(dataset.band_names) == ["B04", "B08"]
    assert dataset.band("B04").to_list() == [1000, 2000, 3000, 500]


def test_the_finest_copy_of_a_band_is_preferred(tmp_path):
    ten = tmp_path / "R10m"
    twenty = tmp_path / "R20m"
    ten.mkdir()
    twenty.mkdir()
    band_file(ten, "T43_B04_10m.tif", [1, 2, 3, 4], 2, 2, GRID_10M)
    band_file(twenty, "T43_B04_20m.tif", [9], 1, 1, GRID_20M)

    bands = discover_scene_bands(str(tmp_path))

    assert len(bands) == 1
    assert "10m" in bands[0]["path"]


def test_a_directory_without_band_files_is_refused(tmp_path):
    (tmp_path / "notes.txt").write_text("nothing here", encoding="utf-8")

    with pytest.raises(RasterError, match="No per-band raster files"):
        open_raster(str(tmp_path))


def test_ndvi_runs_directly_on_a_product_directory(tmp_path):
    product = tmp_path / "S2_PRODUCT"
    product.mkdir()
    band_file(product, "T43_20250311_B04_10m.tif", [1000, 2000, 3000, 500], 2, 2, GRID_10M)
    band_file(product, "T43_20250311_B08_10m.tif", [3000, 2000, 1000, 4500], 2, 2, GRID_10M)

    output = ToolExecutor().run(
        "ndvi", input_references=[str(product)], output_directory=str(tmp_path / "out")
    )

    assert output.statistics["mean"] == pytest.approx(0.2)
    assert output.data["formula"] == "(B08 - B04) / (B08 + B04)"


# ============================================================
# CLOUD MASKING
# ============================================================
@pytest.fixture
def cloudy_scene(raster_factory):
    """Four pixels; the second is cloud (SCL 9) and the third cloud shadow (3).

    NDVI without masking: [0.5, 0.5, 0.5, 0.5] -- the cloud looks like healthy
    vegetation because it is bright in both bands.
    NDVI with masking: only pixels 0 and 3 survive.
    """
    red = make_band("B04", [1000, 1000, 1000, 1000], 4, 1)
    nir = make_band("B08", [3000, 3000, 3000, 3000], 4, 1)
    scl = make_band("SCL", [4, 9, 3, 5], 4, 1, dtype="uint8")
    return raster_factory("cloudy.tif", [red, nir, scl])


def test_masking_excludes_cloud_and_shadow(cloudy_scene, tmp_path):
    output = NDVITool().execute(
        ToolRequest(
            tool_id="ndvi",
            input_references=[cloudy_scene],
            parameters={"mask_band": "SCL"},
            output_directory=str(tmp_path / "out"),
        )
    )

    assert output.statistics["valid_pixels"] == 2
    assert output.statistics["masked_pixels"] == 2
    assert output.statistics["masked_fraction"] == pytest.approx(0.5)

    values = open_raster(output.artifacts[0].path).band_at(1)
    assert values.sample(0, 0) == pytest.approx(0.5)
    assert math.isnan(values.sample(0, 1))  # cloud
    assert math.isnan(values.sample(0, 2))  # cloud shadow
    assert values.sample(0, 3) == pytest.approx(0.5)


def test_without_a_mask_cloud_pixels_are_counted(cloudy_scene, tmp_path):
    # The contrast that makes masking necessary: unmasked, the cloud is
    # indistinguishable from vegetation and inflates the valid count.
    output = NDVITool().execute(
        ToolRequest(
            tool_id="ndvi",
            input_references=[cloudy_scene],
            output_directory=str(tmp_path / "out"),
        )
    )

    assert output.statistics["valid_pixels"] == 4
    assert "masked_pixels" not in output.statistics


def test_excluded_classes_are_reported_by_name(cloudy_scene, tmp_path):
    output = NDVITool().execute(
        ToolRequest(
            tool_id="ndvi",
            input_references=[cloudy_scene],
            parameters={"mask_band": "SCL"},
            output_directory=str(tmp_path / "out"),
        )
    )
    report = output.metadata["mask"]

    assert report["mask_band"] == "SCL"
    assert report["excluded_classes"][9] == "cloud_high_probability"
    assert report["excluded_classes"][3] == "cloud_shadows"
    assert report["class_histogram"]["vegetation"] == 1


def test_the_excluded_classes_can_be_chosen(cloudy_scene, tmp_path):
    # Excluding only high-probability cloud leaves the shadow pixel usable.
    output = NDVITool().execute(
        ToolRequest(
            tool_id="ndvi",
            input_references=[cloudy_scene],
            parameters={"mask_band": "SCL", "mask_invalid_values": "9"},
            output_directory=str(tmp_path / "out"),
        )
    )

    assert output.statistics["valid_pixels"] == 3
    assert output.statistics["masked_pixels"] == 1


def test_an_unresolvable_mask_band_is_reported(cloudy_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="mask band could not be resolved"):
        NDVITool().execute(
            ToolRequest(
                tool_id="ndvi",
                input_references=[cloudy_scene],
                parameters={"mask_band": "QA_PIXEL"},
                output_directory=str(tmp_path / "out"),
            )
        )


def test_malformed_mask_values_are_reported(cloudy_scene, tmp_path):
    with pytest.raises(ToolExecutionError, match="comma-separated list of integers"):
        NDVITool().execute(
            ToolRequest(
                tool_id="ndvi",
                input_references=[cloudy_scene],
                parameters={"mask_band": "SCL", "mask_invalid_values": "cloudy"},
                output_directory=str(tmp_path / "out"),
            )
        )


def test_mask_value_parsing_accepts_both_forms():
    assert parse_mask_values("0,1,3") == (0, 1, 3)
    assert parse_mask_values([8, 9]) == (8, 9)
    assert parse_mask_values(None) is None
    assert parse_mask_values("") is None


def test_default_excluded_classes_are_the_unusable_ones():
    # Snow (11) and dark pixels (2) are real surface, so they stay usable
    # unless the caller says otherwise.
    assert 9 in DEFAULT_SCL_INVALID and 3 in DEFAULT_SCL_INVALID
    assert 11 not in DEFAULT_SCL_INVALID
    assert 2 not in DEFAULT_SCL_INVALID
    assert 4 not in DEFAULT_SCL_INVALID  # vegetation


def test_mask_helper_is_unit_testable(cloudy_scene):
    dataset = open_raster(cloudy_scene)

    mask, report = build_validity_mask(dataset, "SCL")

    assert [bool(value) for value in mask] == [True, False, False, True]
    assert report["masked_pixels"] == 2


def test_change_detection_honours_the_mask(raster_factory, tmp_path):
    # Masking is applied per date, so a cloud on either date removes the pixel
    # from the comparison entirely.
    def dated(name, nir, scl):
        return raster_factory(
            name,
            [
                make_band("B04", [1000, 1000], 2, 1),
                make_band("B08", nir, 2, 1),
                make_band("SCL", scl, 2, 1, dtype="uint8"),
            ],
        )

    earlier = dated("t1.tif", nir=[3000, 3000], scl=[4, 4])
    later = dated("t2.tif", nir=[1000, 3000], scl=[4, 9])  # pixel 1 clouded

    output = ToolExecutor().run(
        "change_detection",
        input_references=[earlier, later],
        parameters={"mask_band": "SCL"},
        output_directory=str(tmp_path / "out"),
    )

    assert output.statistics["valid_pixels"] == 1
    assert output.statistics["nodata_pixels"] == 1
    assert output.statistics["changed_pixels"] == 1


# ============================================================
# QUALITY BANDS AND SENSOR INFERENCE IN REAL PRODUCTS
# ============================================================
def test_quality_layers_are_discovered_alongside_spectral_bands():
    # The cloud mask does not follow the "B04" naming pattern, and without it
    # masking is impossible on a real product.
    assert band_name_from_filename("T43RGM_20250311T053649_SCL_20m.jp2") == "SCL"
    assert band_name_from_filename("LC09_L2SP_147039_20250311_QA_PIXEL.TIF") == "QA_PIXEL"
    assert band_name_from_filename("scene_fmask.tif") == "FMASK"
    assert band_name_from_filename("MTD_MSIL2A.xml") is None


def test_sensor_is_inferred_from_the_product_name():
    from app.tools.raster.scene import sensor_from_product_name

    assert sensor_from_product_name("S2A_MSIL2A_20250311T053649_T43RGM.SAFE") == "sentinel2"
    assert sensor_from_product_name("S2B_MSIL1C_20240101.SAFE") == "sentinel2"
    assert sensor_from_product_name("LC09_L2SP_147039_20250311_02_T1") == "landsat8"
    assert sensor_from_product_name("LE07_L2SP_147039_20200311_02_T1") == "landsat7"
    assert sensor_from_product_name("my_random_folder") is None


def test_a_safe_style_product_resolves_ambiguous_bands(tmp_path):
    # B11 is SWIR on Sentinel-2 but thermal on Landsat-8. Without the sensor,
    # NDBI cannot be computed at all; the product name supplies it.
    root = tmp_path / "S2A_MSIL2A_20250311T053649_T43RGM.SAFE"
    ten = root / "GRANULE" / "L2A" / "IMG_DATA" / "R10m"
    twenty = root / "GRANULE" / "L2A" / "IMG_DATA" / "R20m"
    ten.mkdir(parents=True)
    twenty.mkdir(parents=True)

    band_file(ten, "T43_20250311_B08_10m.tif", [1000] * 16, 4, 4, GRID_10M)
    band_file(twenty, "T43_20250311_B11_20m.tif", [3000] * 4, 2, 2, GRID_20M)
    (root / "MTD_MSIL2A.xml").write_text("<xml/>", encoding="utf-8")

    dataset = open_raster(str(root))
    assert dataset.metadata["sensor"] == "sentinel2"

    output = ToolExecutor().run(
        "ndbi", input_references=[str(root)], output_directory=str(tmp_path / "out")
    )
    assert output.statistics["mean"] == pytest.approx(0.5)


def test_masking_works_on_a_product_directory(tmp_path):
    root = tmp_path / "S2A_MSIL2A_20250311_T43RGM.SAFE"
    ten = root / "R10m"
    twenty = root / "R20m"
    ten.mkdir(parents=True)
    twenty.mkdir(parents=True)

    # Four 10 m pixels; the SCL is 20 m, so one SCL pixel masks all four.
    band_file(ten, "T43_B04_10m.tif", [1000] * 4, 2, 2, GRID_10M)
    band_file(ten, "T43_B08_10m.tif", [3000] * 4, 2, 2, GRID_10M)
    path = str(twenty / "T43_SCL_20m.tif")
    write_raster(
        path, [make_band("SCL", [9], 1, 1, dtype="uint8")], GRID_20M, dtype="uint8"
    )

    output = ToolExecutor().run(
        "ndvi",
        input_references=[str(root)],
        parameters={"mask_band": "SCL"},
        output_directory=str(tmp_path / "out"),
    )

    # The coarse cloud flag was upsampled and removed every fine pixel.
    assert output.statistics["valid_pixels"] == 0
    assert output.statistics["masked_pixels"] == 4


def test_an_unknown_band_name_says_so_rather_than_blaming_the_sensor(tmp_path):
    from app.tools.raster.model import BandResolutionError
    from app.tools.raster.bands import resolve_band

    # Written with no sensor recorded, so band numbers cannot be disambiguated.
    path = str(tmp_path / "anonymous.tif")
    write_raster(
        path, [make_band("B04", [1, 2, 3, 4], 2, 2)], GRID_10M, dtype="uint16"
    )
    dataset = open_raster(path)

    # "B5" genuinely is ambiguous across sensors...
    with pytest.raises(BandResolutionError, match="ambiguous across sensors"):
        resolve_band(dataset, "B5")

    # ...but "SCL" is simply not present, which is a different problem.
    with pytest.raises(BandResolutionError, match="not a recognised band name"):
        resolve_band(dataset, "SCL")
