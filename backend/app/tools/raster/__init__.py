"""Raster data model, band resolution, and backend-selecting raster I/O."""

from app.tools.raster.bands import canonical_name, resolve_band
from app.tools.raster.io import (
    active_backend,
    backend_report,
    has_numpy,
    has_rasterio,
    open_raster,
    write_raster,
)
from app.tools.raster.model import (
    BandArray,
    BandResolutionError,
    GeoReference,
    RasterDataset,
    RasterError,
    UnsupportedRasterError,
    stack_bands,
)

__all__ = [
    "BandArray",
    "BandResolutionError",
    "GeoReference",
    "RasterDataset",
    "RasterError",
    "UnsupportedRasterError",
    "active_backend",
    "backend_report",
    "canonical_name",
    "has_numpy",
    "has_rasterio",
    "open_raster",
    "resolve_band",
    "stack_bands",
    "write_raster",
]
