"""Coordinate reference system operations.

Questions name places in longitude and latitude; rasters are gridded in their
own CRS, usually a UTM zone. Clipping to an area of interest, locating a
finding on the ground, and checking that a question's area overlaps the
imagery all need coordinates moved between the two.

With rasterio installed, PROJ does the work and every CRS it knows is
supported. Without it, WGS 84 geographic coordinates (EPSG:4326) and the WGS 84
UTM zones (EPSG:326xx north, 327xx south) are handled here with Snyder's
Transverse Mercator series (USGS Professional Paper 1395), accurate to well
under a metre within a zone -- which covers Sentinel-2, Landsat and most
analysis-ready products. Any other CRS without rasterio is refused rather than
approximated.
"""

from __future__ import annotations

import math
import re
from typing import Sequence

from app.tools.raster.backends import has_rasterio


class CRSError(Exception):
    """A coordinate transformation cannot be carried out."""


WGS84 = "EPSG:4326"

# WGS 84 ellipsoid.
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9996

_EPSG = re.compile(r"^\s*epsg\s*:\s*(\d+)\s*$", re.IGNORECASE)


def epsg_code(crs: str | None) -> int | None:
    """The EPSG code of ``crs`` when it is written as ``EPSG:nnnn``."""
    if not crs:
        return None
    match = _EPSG.match(str(crs))
    return int(match.group(1)) if match else None


def _utm_zone(code: int) -> tuple[int, bool] | None:
    """``(zone, south)`` for a WGS 84 UTM EPSG code, else ``None``."""
    if 32601 <= code <= 32660:
        return code - 32600, False
    if 32701 <= code <= 32760:
        return code - 32700, True
    return None


def _central_meridian(zone: int) -> float:
    return math.radians((zone - 1) * 6 - 180 + 3)


def lonlat_to_utm(lon: float, lat: float, zone: int, south: bool) -> tuple[float, float]:
    """Forward Transverse Mercator (Snyder 8-9 to 8-10)."""
    phi = math.radians(lat)
    sin_phi, cos_phi, tan_phi = math.sin(phi), math.cos(phi), math.tan(phi)
    n = _A / math.sqrt(1 - _E2 * sin_phi**2)
    t = tan_phi**2
    c = _EP2 * cos_phi**2
    a = cos_phi * (math.radians(lon) - _central_meridian(zone))
    e4, e6 = _E2**2, _E2**3
    m = _A * (
        (1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * _E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )
    x = _K0 * n * (
        a
        + (1 - t + c) * a**3 / 6
        + (5 - 18 * t + t**2 + 72 * c - 58 * _EP2) * a**5 / 120
    ) + 500000.0
    y = _K0 * (
        m
        + n * tan_phi * (
            a**2 / 2
            + (5 - t + 9 * c + 4 * c**2) * a**4 / 24
            + (61 - 58 * t + t**2 + 600 * c - 330 * _EP2) * a**6 / 720
        )
    )
    if south:
        y += 10000000.0
    return x, y


def utm_to_lonlat(x: float, y: float, zone: int, south: bool) -> tuple[float, float]:
    """Inverse Transverse Mercator (Snyder 8-18 to 8-25)."""
    x -= 500000.0
    if south:
        y -= 10000000.0
    e4, e6 = _E2**2, _E2**3
    m = y / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = _A / math.sqrt(1 - _E2 * sin1**2)
    t1 = tan1**2
    c1 = _EP2 * cos1**2
    r1 = _A * (1 - _E2) / (1 - _E2 * sin1**2) ** 1.5
    d = x / (n1 * _K0)
    lat = phi1 - (n1 * tan1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * _EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * _EP2 - 3 * c1**2) * d**6 / 720
    )
    lon = _central_meridian(zone) + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * _EP2 + 24 * t1**2) * d**5 / 120
    ) / cos1
    return math.degrees(lon), math.degrees(lat)


def _needs_rasterio(crs: str) -> CRSError:
    return CRSError(
        f"{crs} needs rasterio; only WGS 84 and its UTM zones are supported without it."
    )


def transform_points(
    xs: Sequence[float], ys: Sequence[float], src: str, dst: str
) -> tuple[list[float], list[float]]:
    """Move points from ``src`` to ``dst``."""
    if src == dst or (epsg_code(src) is not None and epsg_code(src) == epsg_code(dst)):
        return list(xs), list(ys)

    if has_rasterio():
        try:
            from rasterio.warp import transform

            out_x, out_y = transform(src, dst, list(xs), list(ys))
            return list(out_x), list(out_y)
        except Exception as error:  # rasterio raises several CRS error types
            raise CRSError(f"Cannot transform from {src} to {dst}: {error}") from error

    source, target = epsg_code(src), epsg_code(dst)
    if source is None or target is None:
        raise _needs_rasterio(src if source is None else dst)

    # Route everything through longitude and latitude.
    if source == 4326:
        lon, lat = list(xs), list(ys)
    else:
        zone = _utm_zone(source)
        if zone is None:
            raise _needs_rasterio(src)
        pairs = [utm_to_lonlat(x, y, *zone) for x, y in zip(xs, ys)]
        lon, lat = [p[0] for p in pairs], [p[1] for p in pairs]

    if target == 4326:
        return lon, lat
    zone = _utm_zone(target)
    if zone is None:
        raise _needs_rasterio(dst)
    pairs = [lonlat_to_utm(lo, la, *zone) for lo, la in zip(lon, lat)]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def transform_bounds(
    bounds: Sequence[float], src: str, dst: str, densify: int = 21
) -> list[float]:
    """Transform ``[min_x, min_y, max_x, max_y]``, densifying the edges.

    The edges of a box are not straight lines in another projection, so each
    edge is sampled at ``densify`` points and the extent of all of them is
    taken; the corners alone would understate the box.
    """
    min_x, min_y, max_x, max_y = bounds
    xs: list[float] = []
    ys: list[float] = []
    for step in range(densify):
        fraction = step / (densify - 1)
        x = min_x + (max_x - min_x) * fraction
        y = min_y + (max_y - min_y) * fraction
        xs += [x, x, min_x, max_x]
        ys += [min_y, max_y, y, y]
    out_x, out_y = transform_points(xs, ys, src, dst)
    return [min(out_x), min(out_y), max(out_x), max(out_y)]


def to_lonlat(x: float, y: float, crs: str | None) -> tuple[float, float] | None:
    """One point in ``crs`` as longitude and latitude, or ``None`` if impossible."""
    if not crs:
        return None
    try:
        lon, lat = transform_points([x], [y], crs, WGS84)
    except CRSError:
        return None
    return lon[0], lat[0]


__all__ = [
    "CRSError",
    "WGS84",
    "epsg_code",
    "lonlat_to_utm",
    "to_lonlat",
    "transform_bounds",
    "transform_points",
    "utm_to_lonlat",
]
