"""Core raster data model shared by every SatQuery tool.

The model is deliberately backend-agnostic. Band samples live in a flat,
row-major sequence that is either a ``numpy`` array (when numpy is installed)
or an :class:`array.array` from the standard library. Tools operate on the
sequence rather than on the backend, so installing numpy accelerates the whole
tool layer without changing a single tool implementation.
"""

from __future__ import annotations

import array
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

# ============================================================
# SAMPLE TYPES
# ============================================================
# Mapping between the raster dtype names used across the project and the
# `array` module typecodes used to decode raw sample bytes.
DTYPE_TO_TYPECODE: dict[str, str] = {
    "uint8": "B",
    "int8": "b",
    "uint16": "H",
    "int16": "h",
    "uint32": "I",
    "int32": "i",
    "float32": "f",
    "float64": "d",
}

DTYPE_TO_ITEMSIZE: dict[str, int] = {
    "uint8": 1,
    "int8": 1,
    "uint16": 2,
    "int16": 2,
    "uint32": 4,
    "int32": 4,
    "float32": 4,
    "float64": 8,
}


class RasterError(Exception):
    """Base error for every failure raised by the raster layer."""


class UnsupportedRasterError(RasterError):
    """The raster exists but cannot be decoded by the active backend."""


class BandResolutionError(RasterError):
    """A requested band could not be matched to a band in the dataset."""


def new_sample_buffer(dtype: str, size: int, fill: float = 0.0) -> array.array:
    """Allocate a flat sample buffer of ``size`` elements for ``dtype``."""
    typecode = DTYPE_TO_TYPECODE.get(dtype)
    if typecode is None:
        raise UnsupportedRasterError(f"Unsupported raster dtype: {dtype}")
    if typecode in ("f", "d"):
        return array.array(typecode, [float(fill)]) * size
    return array.array(typecode, [int(fill)]) * size


# ============================================================
# GEOREFERENCING
# ============================================================
@dataclass(frozen=True)
class GeoReference:
    """Spatial reference information attached to a raster.

    ``transform`` follows the GDAL geotransform convention:
    ``(origin_x, pixel_width, row_rotation, origin_y, column_rotation, pixel_height)``
    where ``pixel_height`` is normally negative because raster rows run north
    to south.
    """

    crs: str | None = None
    transform: tuple[float, float, float, float, float, float] | None = None

    @property
    def is_georeferenced(self) -> bool:
        return self.crs is not None and self.transform is not None

    @property
    def pixel_size(self) -> tuple[float, float] | None:
        """Return ``(width, height)`` of one pixel in CRS units, or ``None``."""
        if self.transform is None:
            return None
        return abs(self.transform[1]), abs(self.transform[5])

    def pixel_area(self) -> float | None:
        """Return the ground area covered by one pixel in squared CRS units."""
        size = self.pixel_size
        if size is None:
            return None
        return size[0] * size[1]


# ============================================================
# BANDS
# ============================================================
@dataclass
class BandArray:
    """A single raster band held as a flat, row-major sample sequence."""

    name: str
    width: int
    height: int
    values: Any
    dtype: str = "float32"
    nodata: float | None = None

    def __post_init__(self) -> None:
        expected = self.width * self.height
        if len(self.values) != expected:
            raise RasterError(
                f"Band '{self.name}' declares {self.width}x{self.height} "
                f"({expected} samples) but carries {len(self.values)} samples."
            )

    @property
    def size(self) -> int:
        return self.width * self.height

    @property
    def shape(self) -> tuple[int, int]:
        return self.height, self.width

    def sample(self, row: int, column: int) -> float:
        """Return the sample at ``(row, column)`` using row-major indexing."""
        if not 0 <= row < self.height or not 0 <= column < self.width:
            raise IndexError(f"({row}, {column}) is outside {self.shape}")
        return float(self.values[row * self.width + column])

    def to_list(self) -> list[float]:
        return [float(value) for value in self.values]

    def __iter__(self) -> Iterator[float]:
        return (float(value) for value in self.values)


# ============================================================
# DATASETS
# ============================================================
@dataclass
class RasterDataset:
    """An in-memory multi-band raster with its georeferencing and metadata."""

    width: int
    height: int
    bands: list[BandArray]
    georeference: GeoReference = field(default_factory=GeoReference)
    dtype: str = "float32"
    nodata: float | None = None
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for band in self.bands:
            if (band.width, band.height) != (self.width, self.height):
                raise RasterError(
                    f"Band '{band.name}' is {band.width}x{band.height} but the "
                    f"dataset is {self.width}x{self.height}. Bands recorded at "
                    "different resolutions must be resampled before use."
                )

    @property
    def band_names(self) -> list[str]:
        return [band.name for band in self.bands]

    @property
    def band_count(self) -> int:
        return len(self.bands)

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    def band_at(self, index: int) -> BandArray:
        """Return a band by its 1-based index, as used by GDAL and rasterio."""
        if not 1 <= index <= len(self.bands):
            raise BandResolutionError(
                f"Band index {index} is out of range; the dataset has "
                f"{len(self.bands)} band(s)."
            )
        return self.bands[index - 1]

    def band(self, name: str) -> BandArray:
        """Return a band by exact (case-insensitive) name."""
        wanted = name.strip().lower()
        for band in self.bands:
            if band.name.strip().lower() == wanted:
                return band
        raise BandResolutionError(
            f"Band '{name}' is not present. Available bands: {self.band_names}."
        )

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary used in execution metadata."""
        return {
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "band_count": self.band_count,
            "band_names": self.band_names,
            "dtype": self.dtype,
            "nodata": self.nodata,
            "crs": self.georeference.crs,
            "transform": list(self.georeference.transform)
            if self.georeference.transform
            else None,
        }


def stack_bands(
    bands: Sequence[BandArray],
    georeference: GeoReference | None = None,
    **kwargs: Any,
) -> RasterDataset:
    """Build a :class:`RasterDataset` from bands that share a grid."""
    if not bands:
        raise RasterError("At least one band is required to build a dataset.")
    return RasterDataset(
        width=bands[0].width,
        height=bands[0].height,
        bands=list(bands),
        georeference=georeference or GeoReference(),
        **kwargs,
    )
