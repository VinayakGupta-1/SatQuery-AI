"""Shared fixtures that build real GeoTIFF rasters for the tool tests.

These are genuine raster files written to disk by the project's own writer and
read back through its own reader, so the tests exercise the real I/O path. The
pixel values are chosen rather than captured from a satellite, which is what
makes the expected index values checkable by hand -- the arithmetic under test
is real even though the scene is small.
"""

from __future__ import annotations

import array
from typing import Sequence

import pytest

from app.tools.raster.io import write_raster, write_sidecar
from app.tools.raster.model import BandArray, GeoReference

# A 10 m Sentinel-2 style grid in UTM zone 43N, which covers western India.
SENTINEL2_GEOREFERENCE = GeoReference(
    crs="EPSG:32643",
    transform=(699960.0, 10.0, 0.0, 2100000.0, 0.0, -10.0),
)


def make_band(
    name: str,
    values: Sequence[float],
    width: int,
    height: int,
    dtype: str = "uint16",
    nodata: float | None = None,
) -> BandArray:
    """Build a band from an explicit list of samples."""
    typecode = {"uint16": "H", "int16": "h", "float32": "f", "uint8": "B"}[dtype]
    if typecode in ("f",):
        samples = array.array(typecode, [float(value) for value in values])
    else:
        samples = array.array(typecode, [int(value) for value in values])
    return BandArray(
        name=name,
        width=width,
        height=height,
        values=samples,
        dtype=dtype,
        nodata=nodata,
    )


@pytest.fixture
def raster_factory(tmp_path):
    """Return a callable that writes a real multi-band GeoTIFF and its sidecar."""

    def build(
        filename: str,
        bands: list[BandArray],
        georeference: GeoReference | None = SENTINEL2_GEOREFERENCE,
        sensor: str | None = "sentinel2",
        nodata: float | None = None,
        dtype: str | None = None,
    ) -> str:
        path = str(tmp_path / filename)
        metadata = {"band_names": [band.name for band in bands]}
        if sensor:
            metadata["sensor"] = sensor

        # Band names and sensor go *into* the file, so the raster stays
        # self-describing when it is uploaded without its sidecar.
        write_raster(
            path,
            bands,
            georeference,
            dtype=dtype or bands[0].dtype,
            nodata=nodata,
            metadata=metadata,
        )
        write_sidecar(path, metadata)
        return path

    return build


@pytest.fixture
def sentinel2_scene(raster_factory):
    """A 2x2 four-band Sentinel-2 style scene with hand-checkable NDVI.

    Band values (digital numbers) and the NDVI they imply::

        pixel   B4 (red)   B8 (nir)   NDVI = (nir - red) / (nir + red)
        (0,0)       1000       3000    2000 / 4000  =  0.50
        (0,1)       2000       2000       0 / 4000  =  0.00
        (1,0)       3000       1000   -2000 / 4000  = -0.50
        (1,1)        500       4500    4000 / 5000  =  0.80
    """
    width = height = 2
    blue = make_band("B2", [900, 950, 1000, 800], width, height)
    green = make_band("B3", [1200, 1100, 1300, 1000], width, height)
    red = make_band("B4", [1000, 2000, 3000, 500], width, height)
    nir = make_band("B8", [3000, 2000, 1000, 4500], width, height)
    return raster_factory("sentinel2_scene.tif", [blue, green, red, nir])


#: NDVI expected for :func:`sentinel2_scene`, in row-major order.
SENTINEL2_EXPECTED_NDVI = [0.50, 0.00, -0.50, 0.80]
