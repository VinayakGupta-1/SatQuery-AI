"""Turning "Pune", "18.52, 73.85" or a bounding box into an area to fetch.

Coordinates are always preferred to names, and are read deterministically from
what the user typed. Only a place name goes to the geocoder -- OpenStreetMap's
Nominatim -- and the name it resolved to is reported with the answer, so a
"Paris" that came back as Paris, Texas is visible rather than silent.

The area is then sized for analysis. A point becomes a square of
``fetch_default_extent_km``; a place larger than ``fetch_max_extent_km`` -- a
state, say -- is cut to a square of that size around its centre, because
downloading and analysing a whole state is not what a single question can do
in seconds. Either adjustment is recorded as a note.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field

from app.acquisition.web import AcquisitionError, request_json
from app.config.settings import Settings
from app.schemas.spatiotemporal import QueryContext

KM_PER_DEGREE = 111.32

#: Smallest side analysed, in km. A geocoded building or a street is a few
#: dozen metres across: a handful of pixels, not an image.
MIN_EXTENT_KM = 2.0

_NUMBER = r"[-+]?\d{1,3}(?:\.\d+)?"
#: "18.52, 73.85", "18.52°N 73.85°E", "18.52 N, 73.85 E".
POINT_TEXT = re.compile(
    rf"^\s*({_NUMBER})\s*°?\s*([NS])?\s*[,;\s]\s*({_NUMBER})\s*°?\s*([EW])?\s*$",
    re.IGNORECASE,
)
#: Four numbers: west, south, east, north.
BBOX_TEXT = re.compile(
    rf"^\s*\[?\s*({_NUMBER})\s*,\s*({_NUMBER})\s*,\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\]?\s*$"
)
#: Decimal coordinates inside a question: "near 18.52, 73.85" or "(18.52, 73.85)".
POINT_IN_QUERY = re.compile(
    r"(?<![\d.])(-?\d{1,2}\.\d+)\s*°?\s*([NS])?\s*,\s*(-?\d{1,3}\.\d+)\s*°?\s*([EW])?(?![\d.])",
    re.IGNORECASE,
)


@dataclass
class ResolvedArea:
    """Where to fetch, and how that was decided."""

    bbox: list[float]
    name: str
    source: str
    notes: list[str] = field(default_factory=list)

    @property
    def centre(self) -> tuple[float, float]:
        west, south, east, north = self.bbox
        return (west + east) / 2, (south + north) / 2


# ============================================================
# PARSING
# ============================================================
def _signed(value: str, hemisphere: str | None, negative: str) -> float:
    number = float(value)
    if hemisphere and hemisphere.upper() == negative:
        number = -abs(number)
    return number


def parse_point(text: str) -> tuple[float, float] | None:
    """``(lon, lat)`` from "lat, lon" text, or ``None``."""
    match = POINT_TEXT.match(text or "")
    if not match:
        return None
    lat = _signed(match.group(1), match.group(2), "S")
    lon = _signed(match.group(3), match.group(4), "W")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lon, lat


def parse_bbox(text: str) -> list[float] | None:
    """``[west, south, east, north]`` from four comma-separated numbers, or ``None``."""
    match = BBOX_TEXT.match(text or "")
    if not match:
        return None
    west, south, east, north = (float(match.group(i)) for i in range(1, 5))
    west, east = sorted((west, east))
    south, north = sorted((south, north))
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        return None
    return [west, south, east, north]


def point_in_query(query: str) -> tuple[float, float] | None:
    """``(lon, lat)`` of decimal coordinates written in a question, or ``None``."""
    match = POINT_IN_QUERY.search(query or "")
    if not match:
        return None
    lat = _signed(match.group(1), match.group(2), "S")
    lon = _signed(match.group(3), match.group(4), "W")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lon, lat


# ============================================================
# GEOMETRY
# ============================================================
def square_around(lon: float, lat: float, side_km: float) -> list[float]:
    """A square of ``side_km`` centred on a point, in degrees."""
    half_lat = side_km / 2 / KM_PER_DEGREE
    half_lon = side_km / 2 / (KM_PER_DEGREE * max(math.cos(math.radians(lat)), 1e-6))
    return [lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat]


def extent_km(bbox: list[float]) -> tuple[float, float]:
    """``(width, height)`` of a lon/lat box in kilometres, at its mid-latitude."""
    west, south, east, north = bbox
    mid = math.radians((south + north) / 2)
    return (east - west) * KM_PER_DEGREE * math.cos(mid), (north - south) * KM_PER_DEGREE


def fit_extent(
    bbox: list[float],
    centre: tuple[float, float],
    settings: Settings,
    label: str,
) -> tuple[list[float], list[str]]:
    """Grow a tiny area or cut a huge one to a size that can be analysed."""
    width, height = extent_km(bbox)
    largest = float(settings.fetch_max_extent_km)
    if max(width, height) > largest:
        return square_around(*centre, largest), [
            f"{label} spans about {width:.0f} × {height:.0f} km, more than the "
            f"{largest:.0f} km SatQuery fetches for one question, so a "
            f"{largest:.0f} km square around its centre was analysed. Name a "
            "smaller place or give coordinates to analyse a different part."
        ]
    if max(width, height) < MIN_EXTENT_KM:
        side = float(settings.fetch_default_extent_km)
        return square_around(*centre, side), [
            f"{label} is smaller than {MIN_EXTENT_KM:g} km across, so a {side:g} km "
            "square around it was analysed."
        ]
    return bbox, []


def describe_point(lon: float, lat: float) -> str:
    return (
        f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'}, "
        f"{abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"
    )


# ============================================================
# GEOCODING
# ============================================================
#: OpenStreetMap categories that describe an area someone would ask about --
#: a town, a district, a lake, a forest -- rather than a point on it. "Hosur"
#: ranks Hosur railway station above Hosur town; the town is what was meant.
AREA_CATEGORIES = {"place", "boundary", "natural", "waterway", "landuse", "leisure", "water"}

_geocode_cache: dict[str, dict] = {}
_geocode_lock = threading.Lock()
_last_geocode = 0.0


def best_match(results: list[dict]) -> dict:
    """The highest-ranked area among a geocoder's results, else the first result."""
    for result in results:
        if result.get("category") in AREA_CATEGORIES:
            return result
    return results[0]


def geocode(name: str, settings: Settings) -> dict:
    """Look a place name up in Nominatim and return the best match.

    Nominatim's usage policy asks for at most one request a second and an
    identifying User-Agent; both are honoured, and answers are cached for the
    life of the process.
    """
    global _last_geocode
    key = name.strip().lower()
    with _geocode_lock:
        if key in _geocode_cache:
            return _geocode_cache[key]
        wait = 1.0 - (time.monotonic() - _last_geocode)
        if wait > 0:
            time.sleep(wait)
        _last_geocode = time.monotonic()
        results = request_json(
            settings.geocoder_url,
            params={"q": name, "format": "jsonv2", "limit": 5, "accept-language": "en"},
            timeout=settings.fetch_timeout_seconds,
        )
        if not isinstance(results, list) or not results:
            raise AcquisitionError(
                f"No place called '{name}' was found. Check the spelling, add the "
                "state or country, or give coordinates such as '18.52, 73.85'.",
                status="needs_location",
            )
        match = best_match(results)
        _geocode_cache[key] = match
        return match


def _geocoded_area(name: str, settings: Settings, source: str) -> ResolvedArea:
    match = geocode(name, settings)
    try:
        lat, lon = float(match["lat"]), float(match["lon"])
        south, north, west, east = (float(v) for v in match["boundingbox"])
    except (KeyError, TypeError, ValueError) as error:
        raise AcquisitionError(
            f"The geocoder's answer for '{name}' could not be read."
        ) from error
    display = str(match.get("display_name") or name)
    bbox, notes = fit_extent([west, south, east, north], (lon, lat), settings, display.split(",")[0])
    return ResolvedArea(bbox=bbox, name=display, source=source, notes=notes)


# ============================================================
# RESOLUTION
# ============================================================
NO_LOCATION_MESSAGE = (
    "No imagery was attached and the question does not say where to look. Name a "
    "place (for example 'How healthy is the vegetation in Pune?'), give "
    "coordinates such as '18.52, 73.85', fill in the location field, or attach "
    "a GeoTIFF."
)


def resolve_area(
    location: str | None,
    query: str,
    context: QueryContext,
    settings: Settings,
) -> ResolvedArea:
    """Decide where to fetch imagery for a question.

    In order: the explicit ``location`` field (coordinates, a box, or a name);
    a bounding box or coordinates in the question; then the first place name
    in the question. Raises :class:`AcquisitionError` with status
    ``needs_location`` when none of these exists.
    """
    side = float(settings.fetch_default_extent_km)

    if location and location.strip():
        text = location.strip()
        box = parse_bbox(text)
        if box is not None:
            fitted, notes = fit_extent(box, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), settings, "The box")
            return ResolvedArea(fitted, f"box {', '.join(f'{v:.4f}' for v in box)}", "location field", notes)
        point = parse_point(text)
        if point is not None:
            return ResolvedArea(square_around(*point, side), describe_point(*point), "location field")
        return _geocoded_area(text, settings, "location field")

    aoi = context.aoi
    if aoi is not None and aoi.bbox and aoi.crs.upper() == "EPSG:4326":
        box = list(aoi.bbox)
        fitted, notes = fit_extent(box, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), settings, "The area")
        return ResolvedArea(fitted, aoi.describe(), "query coordinates", notes)

    point = point_in_query(query)
    if point is not None:
        return ResolvedArea(square_around(*point, side), describe_point(*point), "query coordinates")

    for name in context.locations:
        return _geocoded_area(name, settings, "geocoded")

    raise AcquisitionError(NO_LOCATION_MESSAGE, status="needs_location")


__all__ = [
    "NO_LOCATION_MESSAGE",
    "ResolvedArea",
    "best_match",
    "extent_km",
    "geocode",
    "parse_bbox",
    "parse_point",
    "point_in_query",
    "resolve_area",
    "square_around",
]
