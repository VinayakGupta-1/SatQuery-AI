"""Tests for the raster model, the GeoTIFF codec, and band resolution."""

from __future__ import annotations

import math

import pytest

from app.tools.raster.bands import canonical_name, resolve_band
from app.tools.raster.io import active_backend, backend_report, open_raster, write_raster
from app.tools.raster.model import (
    BandResolutionError,
    GeoReference,
    RasterError,
    UnsupportedRasterError,
)
from tests.conftest import SENTINEL2_GEOREFERENCE, make_band


# ============================================================
# BACKEND
# ============================================================
def test_backend_report_describes_capabilities():
    report = backend_report()

    assert report["raster_backend"] in ("rasterio", "builtin")
    assert report["raster_backend"] == active_backend()
    assert isinstance(report["numpy_available"], bool)


# ============================================================
# ROUND TRIP
# ============================================================
def test_geotiff_roundtrip_preserves_samples(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    assert dataset.width == 2
    assert dataset.height == 2
    assert dataset.band_count == 4
    assert dataset.band_names == ["B2", "B3", "B4", "B8"]
    assert dataset.band("B4").to_list() == [1000, 2000, 3000, 500]
    assert dataset.band("B8").to_list() == [3000, 2000, 1000, 4500]


def test_geotiff_roundtrip_preserves_georeference(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    assert dataset.georeference.crs == "EPSG:32643"
    assert dataset.georeference.pixel_size == (10.0, 10.0)
    assert dataset.georeference.pixel_area() == 100.0
    assert dataset.georeference.is_georeferenced

    origin_x, pixel_width, _, origin_y, _, pixel_height = dataset.georeference.transform
    assert origin_x == pytest.approx(699960.0)
    assert origin_y == pytest.approx(2100000.0)
    assert pixel_width == pytest.approx(10.0)
    assert pixel_height == pytest.approx(-10.0)


def test_float32_roundtrip_preserves_values(raster_factory):
    band = make_band("NDVI", [-1.0, -0.25, 0.5, 1.0], 2, 2, dtype="float32")
    path = raster_factory("float.tif", [band], sensor=None, dtype="float32")

    dataset = open_raster(path)

    assert dataset.dtype == "float32"
    assert dataset.band_at(1).to_list() == pytest.approx([-1.0, -0.25, 0.5, 1.0])


def test_nodata_is_preserved(raster_factory):
    band = make_band("B4", [1, 2, 3, 4], 2, 2, nodata=0)
    path = raster_factory("nodata.tif", [band], nodata=0)

    dataset = open_raster(path)

    assert dataset.nodata == 0


def test_single_row_raster_roundtrips(raster_factory):
    band = make_band("B4", [10, 20, 30, 40, 50], 5, 1)
    path = raster_factory("strip.tif", [band])

    dataset = open_raster(path)

    assert (dataset.width, dataset.height) == (5, 1)
    assert dataset.band_at(1).to_list() == [10, 20, 30, 40, 50]


def test_band_sample_uses_row_major_indexing(sentinel2_scene):
    red = open_raster(sentinel2_scene).band("B4")

    assert red.sample(0, 0) == 1000
    assert red.sample(0, 1) == 2000
    assert red.sample(1, 0) == 3000
    assert red.sample(1, 1) == 500

    with pytest.raises(IndexError):
        red.sample(2, 0)


def test_describe_is_serialisable(sentinel2_scene):
    description = open_raster(sentinel2_scene).describe()

    assert description["band_names"] == ["B2", "B3", "B4", "B8"]
    assert description["crs"] == "EPSG:32643"
    assert description["width"] == 2
    assert isinstance(description["transform"], list)


# ============================================================
# FAILURE MODES
# ============================================================
def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(RasterError, match="not found"):
        open_raster(str(tmp_path / "absent.tif"))


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.tif"
    path.write_bytes(b"")

    with pytest.raises(RasterError, match="empty"):
        open_raster(str(path))


def test_non_raster_file_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("this is not a raster", encoding="utf-8")

    with pytest.raises(RasterError):
        open_raster(str(path))


def test_blank_path_is_rejected():
    with pytest.raises(RasterError):
        open_raster("   ")


def test_writing_without_bands_is_rejected(tmp_path):
    with pytest.raises(RasterError):
        write_raster(str(tmp_path / "out.tif"), [])


def test_mismatched_band_grids_are_rejected(tmp_path):
    wide = make_band("B4", [1, 2, 3, 4], 4, 1)
    tall = make_band("B8", [1, 2, 3, 4], 1, 4)

    with pytest.raises(RasterError):
        write_raster(str(tmp_path / "mixed.tif"), [wide, tall])


def test_band_declaring_wrong_size_is_rejected():
    with pytest.raises(RasterError, match="samples"):
        make_band("B4", [1, 2, 3], 2, 2)


def test_unsupported_dtype_is_rejected(tmp_path):
    band = make_band("B4", [1, 2, 3, 4], 2, 2)
    band.dtype = "complex64"

    with pytest.raises(UnsupportedRasterError):
        write_raster(str(tmp_path / "complex.tif"), [band], dtype="complex64")


# ============================================================
# BAND RESOLUTION
# ============================================================
def test_resolve_band_by_exact_name(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    assert resolve_band(dataset, "B8").name == "B8"
    assert resolve_band(dataset, "b8").name == "B8"


def test_resolve_band_by_logical_name(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    assert resolve_band(dataset, "red").name == "B4"
    assert resolve_band(dataset, "nir").name == "B8"
    assert resolve_band(dataset, "green").name == "B3"


def test_resolve_band_by_index(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    assert resolve_band(dataset, 1).name == "B2"
    assert resolve_band(dataset, "4").name == "B8"


def test_resolve_band_rejects_absent_band(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    with pytest.raises(BandResolutionError, match="swir"):
        resolve_band(dataset, "swir")


def test_resolve_band_rejects_out_of_range_index(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    with pytest.raises(BandResolutionError, match="out of range"):
        resolve_band(dataset, 9)


def test_sensor_changes_band_meaning():
    # B5 is red-edge on Sentinel-2 but near-infrared on Landsat-8. Getting this
    # wrong would silently compute an index from the wrong wavelengths.
    assert canonical_name("B5", "sentinel2") == "red_edge"
    assert canonical_name("B5", "landsat8") == "nir"
    assert canonical_name("SR_B5", "landsat8") == "nir"


def test_ambiguous_band_without_sensor_is_refused():
    assert canonical_name("B5") is None
    assert canonical_name("B4") == "red"


def test_ambiguous_band_resolution_reports_clearly(raster_factory):
    bands = [
        make_band("B4", [1, 2, 3, 4], 2, 2),
        make_band("B5", [1, 2, 3, 4], 2, 2),
    ]
    path = raster_factory("ambiguous.tif", bands, sensor=None)
    dataset = open_raster(path)

    # The band is present by name, so an exact request still succeeds...
    assert resolve_band(dataset, "B5").name == "B5"

    # ...but a logical request that depends on the sensor must not guess.
    with pytest.raises(BandResolutionError, match="not present"):
        resolve_band(dataset, "nir")


def test_sidecar_supplies_band_names_and_sensor(sentinel2_scene):
    dataset = open_raster(sentinel2_scene)

    assert dataset.metadata["sensor"] == "sentinel2"
    assert dataset.metadata["band_names"] == ["B2", "B3", "B4", "B8"]


def test_georeference_without_transform_has_no_pixel_area():
    reference = GeoReference(crs="EPSG:4326")

    assert reference.pixel_size is None
    assert reference.pixel_area() is None
    assert not reference.is_georeferenced


def test_geographic_crs_roundtrips(raster_factory):
    band = make_band("B4", [1, 2, 3, 4], 2, 2)
    reference = GeoReference(
        crs="EPSG:4326", transform=(77.0, 0.0001, 0.0, 28.0, 0.0, -0.0001)
    )
    path = raster_factory("wgs84.tif", [band], georeference=reference)

    dataset = open_raster(path)

    assert dataset.georeference.crs == "EPSG:4326"
    assert dataset.georeference.transform[0] == pytest.approx(77.0)
    assert not math.isnan(dataset.georeference.transform[1])
