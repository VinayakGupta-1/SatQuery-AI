"""Cross-backend tests: the built-in codec and rasterio must agree.

The built-in GeoTIFF codec exists so SatQuery runs without GDAL. That is only
worth having if the files it writes are genuine GeoTIFFs that other software
can read, and if it reads what other software writes. These tests check both
directions against rasterio whenever rasterio is installed, and skip cleanly
when it is not.

The whole suite can also be run against the built-in backend on a machine that
has rasterio, by setting ``SATQUERY_RASTER_BACKEND=builtin``.
"""

from __future__ import annotations

import array

import pytest

from app.tools.raster import tiff
from app.tools.raster.io import BACKEND_ENV_VAR, has_rasterio, open_raster, write_raster
from app.tools.raster.model import BandArray, GeoReference

rasterio = pytest.importorskip("rasterio", reason="cross-backend checks need rasterio")

GEOREFERENCE = GeoReference(
    crs="EPSG:32643",
    transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0),
)


@pytest.fixture
def builtin_backend(monkeypatch):
    """Force the dependency-free backend for the duration of a test."""
    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    assert not has_rasterio()


def make_band(name, values, width, height, dtype="uint16"):
    typecode = {"uint16": "H", "int16": "h", "float32": "f", "uint8": "B"}[dtype]
    caster = float if typecode == "f" else int
    return BandArray(
        name=name,
        width=width,
        height=height,
        values=array.array(typecode, [caster(value) for value in values]),
        dtype=dtype,
    )


# ============================================================
# THE BUILT-IN WRITER PRODUCES REAL GEOTIFFS
# ============================================================
def test_gdal_can_read_what_the_builtin_codec_writes(tmp_path, builtin_backend):
    path = str(tmp_path / "builtin.tif")
    bands = [
        make_band("B4", [1000, 2000, 3000, 500], 2, 2),
        make_band("B8", [3000, 2000, 1000, 4500], 2, 2),
    ]
    write_raster(path, bands, GEOREFERENCE, dtype="uint16")

    # Read it back with GDAL rather than with our own codec.
    with rasterio.open(path) as source:
        assert source.width == 2
        assert source.height == 2
        assert source.count == 2
        assert str(source.crs) == "EPSG:32643"
        assert source.read(1).reshape(-1).tolist() == [1000, 2000, 3000, 500]
        assert source.read(2).reshape(-1).tolist() == [3000, 2000, 1000, 4500]

        assert source.transform.c == pytest.approx(699960.0)
        assert source.transform.f == pytest.approx(2100000.0)
        assert source.transform.a == pytest.approx(10.0)
        assert source.transform.e == pytest.approx(-10.0)


def test_gdal_reads_builtin_float_output(tmp_path, builtin_backend):
    path = str(tmp_path / "index.tif")
    band = make_band("NDVI", [-1.0, -0.25, 0.5, 1.0], 2, 2, dtype="float32")
    write_raster(path, [band], GEOREFERENCE, dtype="float32")

    with rasterio.open(path) as source:
        assert source.dtypes[0] == "float32"
        assert source.read(1).reshape(-1).tolist() == pytest.approx([-1.0, -0.25, 0.5, 1.0])


# ============================================================
# THE BUILT-IN READER HANDLES WHAT GDAL WRITES
# ============================================================
def test_builtin_codec_reads_an_uncompressed_gdal_geotiff(tmp_path, monkeypatch):
    import numpy

    path = str(tmp_path / "gdal.tif")
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=3, count=2,
        dtype="uint16", crs="EPSG:32643",
        transform=rasterio.transform.Affine(10.0, 0.0, 699960.0, 0.0, -10.0, 2100000.0),
        compress="none",
    ) as destination:
        destination.write(numpy.arange(12, dtype="uint16").reshape(3, 4), 1)
        destination.write(numpy.arange(100, 112, dtype="uint16").reshape(3, 4), 2)

    # Now read it with the dependency-free codec.
    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    dataset = open_raster(path)

    assert (dataset.width, dataset.height) == (4, 3)
    assert dataset.band_count == 2
    assert dataset.dtype == "uint16"
    assert dataset.band_at(1).to_list() == list(range(12))
    assert dataset.band_at(2).to_list() == list(range(100, 112))
    assert dataset.georeference.crs == "EPSG:32643"
    assert dataset.georeference.pixel_size == (10.0, 10.0)


def test_builtin_codec_reads_a_tiled_gdal_geotiff(tmp_path, monkeypatch):
    import numpy

    # Tiling is common in real satellite products and uses a different layout
    # from strips, so it needs its own check.
    path = str(tmp_path / "tiled.tif")
    values = numpy.arange(64 * 64, dtype="uint16").reshape(64, 64)
    with rasterio.open(
        path, "w", driver="GTiff", width=64, height=64, count=1,
        dtype="uint16", crs="EPSG:32643",
        transform=rasterio.transform.Affine(10.0, 0.0, 699960.0, 0.0, -10.0, 2100000.0),
        tiled=True, blockxsize=16, blockysize=16, compress="none",
    ) as destination:
        destination.write(values, 1)

    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    dataset = open_raster(path)

    assert dataset.band_at(1).to_list() == values.reshape(-1).tolist()


def test_builtin_codec_refuses_compressed_geotiff_clearly(tmp_path, monkeypatch):
    import numpy

    from app.tools.raster.model import UnsupportedRasterError

    path = str(tmp_path / "deflate.tif")
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=4, count=1,
        dtype="uint16", compress="deflate",
    ) as destination:
        destination.write(numpy.ones((4, 4), dtype="uint16"), 1)

    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")

    # It must say what to do, not fail obscurely or return wrong pixels.
    with pytest.raises(UnsupportedRasterError, match="rasterio"):
        open_raster(path)

    # With rasterio permitted again, the same file reads fine.
    monkeypatch.delenv(BACKEND_ENV_VAR)
    assert open_raster(path).band_at(1).to_list() == [1] * 16


# ============================================================
# THE TWO BACKENDS AGREE ON RESULTS
# ============================================================
def test_ndvi_is_identical_under_both_backends(tmp_path, monkeypatch):
    from app.tools.executor import ToolExecutor
    from app.tools.raster.io import write_sidecar

    path = str(tmp_path / "scene.tif")
    red = make_band("B4", [1000, 2000, 3000, 500], 2, 2)
    nir = make_band("B8", [3000, 2000, 1000, 4500], 2, 2)
    write_raster(path, [red, nir], GEOREFERENCE, dtype="uint16")
    write_sidecar(path, {"band_names": ["B4", "B8"], "sensor": "sentinel2"})

    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    builtin = ToolExecutor().run(
        "ndvi", input_references=[path], output_directory=str(tmp_path / "a")
    )

    monkeypatch.delenv(BACKEND_ENV_VAR)
    with_gdal = ToolExecutor().run(
        "ndvi", input_references=[path], output_directory=str(tmp_path / "b")
    )

    assert builtin.metadata["raster_backend"] == "builtin"
    assert with_gdal.metadata["raster_backend"] == "rasterio"

    for key in ("mean", "minimum", "maximum", "standard_deviation"):
        assert builtin.statistics[key] == pytest.approx(with_gdal.statistics[key])
    assert builtin.statistics["valid_pixels"] == with_gdal.statistics["valid_pixels"]
    assert builtin.data["classes"] == with_gdal.data["classes"]


def test_builtin_reader_matches_gdal_reader_on_the_same_file(tmp_path, monkeypatch):
    path = str(tmp_path / "shared.tif")
    band = make_band("B4", list(range(20)), 5, 4)
    write_raster(path, [band], GEOREFERENCE, dtype="uint16")

    with_gdal = open_raster(path)

    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    builtin = open_raster(path)

    assert builtin.band_at(1).to_list() == with_gdal.band_at(1).to_list()
    assert builtin.georeference.crs == with_gdal.georeference.crs
    assert builtin.georeference.transform == pytest.approx(with_gdal.georeference.transform)
    assert builtin.dtype == with_gdal.dtype


# ============================================================
# BAND IDENTITY SURVIVES INSIDE THE FILE
# ============================================================
def test_band_names_survive_without_a_sidecar(tmp_path, monkeypatch):
    # An upload arrives as a bare .tif. If band names only lived in a sidecar,
    # the file would lose its identity in transit and NDVI could not find NIR.
    path = str(tmp_path / "named.tif")
    bands = [make_band("B4", [1, 2, 3, 4], 2, 2), make_band("B8", [5, 6, 7, 8], 2, 2)]
    write_raster(
        path, bands, GEOREFERENCE, dtype="uint16", metadata={"sensor": "sentinel2"}
    )
    assert not (tmp_path / "named.tif.satquery.json").exists()

    for backend in ("rasterio", "builtin"):
        monkeypatch.setenv(BACKEND_ENV_VAR, "builtin" if backend == "builtin" else "")
        dataset = open_raster(path)
        assert dataset.band_names == ["B4", "B8"], backend
        assert dataset.metadata.get("sensor") == "sentinel2", backend


def test_gdal_reads_band_names_written_by_the_builtin_codec(tmp_path, monkeypatch):
    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    path = str(tmp_path / "builtin_named.tif")
    write_raster(
        path,
        [make_band("B4", [1, 2, 3, 4], 2, 2), make_band("B8", [5, 6, 7, 8], 2, 2)],
        GEOREFERENCE,
        dtype="uint16",
        metadata={"sensor": "sentinel2"},
    )

    # GDAL must see the same band descriptions our codec wrote.
    with rasterio.open(path) as source:
        assert list(source.descriptions) == ["B4", "B8"]
        assert source.tags().get("sensor") == "sentinel2"


def test_ndvi_resolves_bands_from_file_metadata_alone(tmp_path, monkeypatch):
    from app.tools.executor import ToolExecutor

    monkeypatch.setenv(BACKEND_ENV_VAR, "builtin")
    path = str(tmp_path / "bare.tif")
    write_raster(
        path,
        [
            make_band("B4", [1000, 2000, 3000, 500], 2, 2),
            make_band("B8", [3000, 2000, 1000, 4500], 2, 2),
        ],
        GEOREFERENCE,
        dtype="uint16",
        metadata={"sensor": "sentinel2"},
    )

    output = ToolExecutor().run(
        "ndvi", input_references=[path], output_directory=str(tmp_path / "out")
    )

    assert output.data["formula"] == "(B8 - B4) / (B8 + B4)"
    assert output.statistics["mean"] == pytest.approx(0.2)


# ============================================================
# THE CODEC ITSELF
# ============================================================
def test_big_endian_tiff_is_decoded(tmp_path):
    # Our writer emits little-endian; GDAL is the easiest source of a
    # big-endian file, via its byte-order creation option.
    import numpy

    path = str(tmp_path / "bigendian.tif")
    try:
        with rasterio.open(
            path, "w", driver="GTiff", width=3, height=2, count=1,
            dtype="uint16", compress="none", BIGTIFF="NO", ENDIANNESS="BIG",
        ) as destination:
            destination.write(numpy.array([[1, 2, 3], [4, 5, 6]], dtype="uint16"), 1)
    except Exception:  # pragma: no cover - depends on the GDAL build
        pytest.skip("this GDAL build does not honour ENDIANNESS=BIG")

    with open(path, "rb") as handle:
        if handle.read(2) != b"MM":  # pragma: no cover
            pytest.skip("GDAL did not produce a big-endian file")

    dataset = tiff.read_tiff(path)
    assert dataset.band_at(1).to_list() == [1, 2, 3, 4, 5, 6]
