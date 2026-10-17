"""Reading only the area of interest out of remote cloud-optimised GeoTIFFs.

A Sentinel-2 band file covers 110 km at 10 m: about 120 million pixels. A
question about one city needs a few hundred thousand of them. GDAL reads a
cloud-optimised GeoTIFF over HTTP range requests, so each band is opened
remotely and only the blocks that overlap the area are transferred.

Every band, from every tile, is warped onto one *grid* -- the same coordinate
system, origin, pixel size and dimensions. That is what lets bands of
different resolutions be stacked into one image, lets two tiles of a pass be
mosaicked, and lets a before and an after image be compared pixel for pixel
without any later resampling.

Resampling is chosen so values are never invented: class codes (SCL) are
always taken from the nearest pixel; measurements are averaged when the grid
is coarser than the file and taken from the nearest pixel when it is finer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app import USER_AGENT
from app.acquisition.web import AcquisitionError
from app.config.settings import Settings
from app.tools.raster.backends import has_rasterio
from app.tools.raster.crs import transform_bounds

#: GDAL options for reading cloud-optimised GeoTIFFs over HTTP: do not list
#: remote "directories", merge adjacent byte ranges, and retry transient errors.
GDAL_HTTP_OPTIONS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "1",
    "GDAL_HTTP_USERAGENT": USER_AGENT,
    "VSI_CACHE": "TRUE",
}


@dataclass(frozen=True)
class Grid:
    """The pixel grid every band of a request is read onto."""

    crs: str
    #: GDAL order: ``(origin_x, pixel_width, 0, origin_y, 0, -pixel_height)``.
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int
    resolution: float


def make_grid(bbox_lonlat: list[float], epsg: int, settings: Settings) -> Grid:
    """A grid in ``epsg`` covering ``bbox_lonlat``, at 10 m or coarser.

    The pixel size is the finest of 10, 20, 40, 80 m ... that keeps the longest
    side within ``fetch_max_pixels``. Those are the files' own overview levels,
    so a coarse grid is read from an overview of exactly its size: nothing is
    downloaded only to be averaged away. The origin is snapped to a whole
    number of pixels so grids built for the same area always coincide.
    """
    crs = f"EPSG:{epsg}"
    west, south, east, north = transform_bounds(bbox_lonlat, "EPSG:4326", crs)
    longest = max(east - west, north - south)
    resolution = 10.0
    while longest / resolution > max(settings.fetch_max_pixels, 1):
        resolution *= 2
    origin_x = math.floor(west / resolution) * resolution
    origin_y = math.ceil(north / resolution) * resolution
    width = max(1, math.ceil((east - origin_x) / resolution))
    height = max(1, math.ceil((origin_y - south) / resolution))
    return Grid(
        crs=crs,
        transform=(origin_x, resolution, 0.0, origin_y, 0.0, -resolution),
        width=width,
        height=height,
        resolution=resolution,
    )


def _overview_level(source: Any, resolution: float) -> int | None:
    """The coarsest overview still at least as fine as ``resolution``."""
    native = abs(source.res[0])
    level = None
    for index, factor in enumerate(source.overviews(1) or []):
        if native * factor <= resolution * 1.001:
            level = index
    return level


def read_asset(
    href: str,
    grid: Grid,
    categorical: bool,
    nodata: float,
) -> Any:
    """Read one remote band onto ``grid`` and return a 2-D numpy array.

    Pixels the file has no data for are ``nodata``.
    """
    if not has_rasterio():
        raise AcquisitionError(
            "Fetching imagery needs rasterio (pip install rasterio); the built-in "
            "raster backend cannot read remote cloud-optimised GeoTIFFs."
        )
    import numpy
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.vrt import WarpedVRT

    origin_x, pixel_w, _, origin_y, _, pixel_h = grid.transform
    affine = Affine(pixel_w, 0.0, origin_x, 0.0, pixel_h, origin_y)

    def warp(source: Any, resampling: Any) -> Any:
        with WarpedVRT(
            source,
            crs=grid.crs,
            transform=affine,
            width=grid.width,
            height=grid.height,
            resampling=resampling,
            nodata=nodata,
        ) as warped:
            return numpy.asarray(warped.read(1))

    try:
        with rasterio.Env(**GDAL_HTTP_OPTIONS):
            with rasterio.open(href) as source:
                native = abs(source.res[0])
                if categorical or grid.resolution <= native * 1.001:
                    resampling = Resampling.nearest
                else:
                    resampling = Resampling.average
                level = _overview_level(source, grid.resolution)
                if level is None:
                    return warp(source, resampling)
            # A coarser grid is read from the file's own overview, which holds
            # a fraction of the bytes of the full-resolution band.
            with rasterio.open(href, overview_level=level) as overview:
                return warp(overview, resampling)
    except AcquisitionError:
        raise
    except Exception as error:  # rasterio raises many error types for remote reads
        name = href.split("?")[0].rsplit("/", 1)[-1]
        raise AcquisitionError(f"Reading {name} from the imagery provider failed: {error}") from error


__all__ = ["GDAL_HTTP_OPTIONS", "Grid", "make_grid", "read_asset"]
