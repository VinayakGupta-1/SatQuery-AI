"""Reading where, when, what measure and which sensor a question is about.

Intent is only one part of a question. "How much vegetation was lost in the
north-west between 2023 and 2025?" also names a region, a period and a metric,
and each of those changes what a correct answer is. This module extracts them
from the literal sentence:

*Location* -- coordinates or a bounding box become an area of interest; a named
part of the scene ("the northern half") becomes one too; place names are kept
as written. Nothing here geocodes them: with uploaded imagery SatQuery reports
them next to the imagery's own footprint and lets the user judge whether the
two match; without imagery, :mod:`app.acquisition.location` looks the first one
up to decide where to fetch a scene, and reports the place it resolved to.

*Time* -- explicit dates, months and years become a period the validator then
checks every acquisition date against.

*Metric* -- area, percentage, mean, count and so on, which decide what the
answer leads with.

*Modality* -- whether the sentence speaks of optical imagery, radar, or both.

Everything here is deterministic on purpose. A language model may propose the
task, but values that change what is computed -- coordinates, dates, regions --
come only from the words the user typed, never from a model's paraphrase of
them. A hallucinated bounding box would otherwise clip the wrong ground and
return a confident answer about somewhere else.
"""

from __future__ import annotations

import calendar
import math
import re
from datetime import date

from app.schemas.spatiotemporal import AreaOfInterest, QueryContext, TimeRange

# ============================================================
# TIME
# ============================================================
_YEAR = r"(19[7-9]\d|20[0-4]\d)"

#: A year, unless it is part of a decimal, another number, or a measurement.
YEAR_PATTERN = re.compile(
    r"(?<![\d.])(?<!pixel )(?<!pixels )(?<!band )(?<!value )" + _YEAR + r"(?!\.\d)(?!\d)"
    r"(?!\s*(?:m\b|km|ha\b|hectares?|pixels?|px\b|metres?|meters?|%|sq\b|dn\b))",
    re.IGNORECASE,
)
ISO_DATE_PATTERN = re.compile(
    r"(?<![\d.])" + _YEAR + r"-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)"
)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_YEAR_PATTERN = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\.?,?\s+" + _YEAR + r"(?!\d)",
    re.IGNORECASE,
)
OPEN_START = re.compile(r"\b(since|after|from)\s*$", re.IGNORECASE)
OPEN_END = re.compile(r"\b(before|until|till|up to|prior to|by)\s*$", re.IGNORECASE)


def _mentions(query: str) -> list[tuple[int, int, date, date]]:
    """Every date-like mention as ``(start, end, first_day, last_day)``."""
    found: list[tuple[int, int, date, date]] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in taken)

    for match in ISO_DATE_PATTERN.finditer(query):
        day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        found.append((match.start(), match.end(), day, day))
        taken.append(match.span())

    for match in MONTH_YEAR_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        month = MONTHS[match.group(1)[:3].lower()]
        year = int(match.group(2))
        last = calendar.monthrange(year, month)[1]
        found.append((match.start(), match.end(), date(year, month, 1), date(year, month, last)))
        taken.append(match.span())

    for match in YEAR_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        year = int(match.group(1))
        found.append((match.start(), match.end(), date(year, 1, 1), date(year, 12, 31)))
        taken.append(match.span())

    return sorted(found)


def extract_time_range(query: str) -> TimeRange | None:
    """The period a question names, or ``None`` when it names none."""
    mentions = _mentions(query)
    if not mentions:
        return None

    text = query[mentions[0][0]:mentions[-1][1]]
    if len(mentions) >= 2:
        return TimeRange(
            start=min(m[2] for m in mentions),
            end=max(m[3] for m in mentions),
            text=text,
        )

    start, end, first, last = mentions[0]
    before = query[:start]
    opener = OPEN_START.search(before)
    if opener:
        return TimeRange(start=first, end=None, text=query[opener.start():end])
    closer = OPEN_END.search(before)
    if closer:
        return TimeRange(start=None, end=last, text=query[closer.start():end])
    return TimeRange(start=first, end=last, text=text)


def extract_periods(query: str) -> list[TimeRange]:
    """Each date, month or year the question names, as its own period, in order.

    :func:`extract_time_range` merges "between 2020 and 2024" into one range,
    which is right for checking acquisition dates. Fetching a before and an
    after image needs the two ends apart: one scene from 2020, one from 2024.
    """
    return [
        TimeRange(start=first, end=last, text=query[start:end])
        for start, end, first, last in _mentions(query)
    ]


# ============================================================
# LOCATION
# ============================================================
_NUMBER = r"(-?\d{1,3}(?:\.\d+)?)"

BBOX_PATTERN = re.compile(
    r"\b(?:bbox|bounding\s+box)\s*[:=]?\s*\(?\[?\s*" + _NUMBER + r"\s*,\s*" + _NUMBER
    + r"\s*,\s*" + _NUMBER + r"\s*,\s*" + _NUMBER,
    re.IGNORECASE,
)
LAT_RANGE_PATTERN = re.compile(
    r"\blat(?:itude)?s?\s*(?:between|from)?\s*" + _NUMBER + r"\s*°?\s*[ns]?\s*(?:to|and|-|–)\s*"
    + _NUMBER,
    re.IGNORECASE,
)
LON_RANGE_PATTERN = re.compile(
    r"\blon(?:g|gitude)?s?\s*(?:between|from)?\s*" + _NUMBER + r"\s*°?\s*[ew]?\s*(?:to|and|-|–)\s*"
    + _NUMBER,
    re.IGNORECASE,
)
POINT_PATTERN = re.compile(
    r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*°?\s*([NS])?\s*,?\s+(\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])?(?![\d.])"
    r"|\(\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*\)",
    re.IGNORECASE,
)
RADIUS_PATTERN = re.compile(
    r"\bwithin\s+(\d+(?:\.\d+)?)\s*(km|kilomet(?:re|er)s?|m|met(?:re|er)s?)\b", re.IGNORECASE
)

_DIRECTION = r"(north|south|east|west)[\s-]?(east|west)?(?:ern)?"
_PART = r"(half|part|quadrant|corner|side|portion|section|region|area|edge)"
#: "The northern part of Maharashtra" is about a place, not about the image, so
#: a part followed by "of <something other than the image>" is not a region.
_OF_SOMEWHERE_ELSE = r"(?!\s+of\s+(?!(?:the|this)\s+(?:image|scene|picture|tile|raster)\b))"
REGION_PATTERN = re.compile(
    r"\b" + _DIRECTION + r"\s+" + _PART + r"\b" + _OF_SOMEWHERE_ELSE, re.IGNORECASE
)
SCREEN_REGION_PATTERN = re.compile(
    r"\b(top|bottom|upper|lower)[\s-]?(left|right)?\s+" + _PART + r"\b" + _OF_SOMEWHERE_ELSE,
    re.IGNORECASE,
)
CENTRE_PATTERN = re.compile(
    r"\b(?:in|at)\s+the\s+(?:centre|center|middle)(?:\s+of\s+the\s+(?:image|scene|area))?\b",
    re.IGNORECASE,
)

PLACE_PATTERN = re.compile(
    r"\b(?:in|over|near|around|across|at|for|of)\s+(?:the\s+)?"
    r"((?:[A-Z][a-zA-Z'-]+)(?:\s+[A-Z][a-zA-Z'-]+){0,3})"
)
NOT_PLACES = {
    "this", "that", "these", "those", "the", "image", "images", "scene", "scenes",
    "sentinel", "landsat", "cartosat", "resourcesat", "risat", "january", "february",
    "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "north", "south", "east", "west", "i", "it", "my", "our",
}


def _point_bbox(lat: float, lon: float, radius_km: float) -> list[float]:
    """A square of half-side ``radius_km`` around a point, in lon/lat."""
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _valid_lonlat(bbox: list[float]) -> bool:
    min_x, min_y, max_x, max_y = bbox
    return -180 <= min_x < max_x <= 180 and -90 <= min_y < max_y <= 90


def extract_aoi(query: str) -> AreaOfInterest | None:
    """An area of interest stated in the question, or ``None``."""
    match = BBOX_PATTERN.search(query)
    if match:
        values = [float(match.group(i)) for i in range(1, 5)]
        bbox = [min(values[0], values[2]), min(values[1], values[3]),
                max(values[0], values[2]), max(values[1], values[3])]
        if _valid_lonlat(bbox):
            return AreaOfInterest(bbox=bbox, text=match.group(0))

    lat, lon = LAT_RANGE_PATTERN.search(query), LON_RANGE_PATTERN.search(query)
    if lat and lon:
        lats = sorted([float(lat.group(1)), float(lat.group(2))])
        lons = sorted([float(lon.group(1)), float(lon.group(2))])
        bbox = [lons[0], lats[0], lons[1], lats[1]]
        if _valid_lonlat(bbox):
            return AreaOfInterest(bbox=bbox, text=f"{lat.group(0)}, {lon.group(0)}")

    radius = RADIUS_PATTERN.search(query)
    point = POINT_PATTERN.search(query)
    if radius and point:
        if point.group(1) is not None:
            lat_value, lon_value = float(point.group(1)), float(point.group(3))
            if (point.group(2) or "N").upper() == "S":
                lat_value = -lat_value
            if (point.group(4) or "E").upper() == "W":
                lon_value = -lon_value
        else:
            lat_value, lon_value = float(point.group(5)), float(point.group(6))
        distance = float(radius.group(1))
        km = distance if radius.group(2).lower().startswith("k") else distance / 1000.0
        bbox = _point_bbox(lat_value, lon_value, km)
        if km > 0 and _valid_lonlat(bbox):
            return AreaOfInterest(bbox=bbox, text=f"{radius.group(0)} of {point.group(0).strip()}")

    region = _named_region(query)
    if region:
        return region
    return None


def _named_region(query: str) -> AreaOfInterest | None:
    match = REGION_PATTERN.search(query)
    if match:
        first, second, part = match.group(1).lower(), (match.group(2) or "").lower(), match.group(3).lower()
        if second and first in {"north", "south"}:
            return AreaOfInterest(region=f"{first}_{second}", text=match.group(0))
        if not second:
            return AreaOfInterest(region=first, text=match.group(0))
    match = SCREEN_REGION_PATTERN.search(query)
    if match:
        vertical = "north" if match.group(1).lower() in {"top", "upper"} else "south"
        horizontal = (match.group(2) or "").lower()
        if horizontal:
            side = "west" if horizontal == "left" else "east"
            return AreaOfInterest(region=f"{vertical}_{side}", text=match.group(0))
        return AreaOfInterest(region=vertical, text=match.group(0))
    match = CENTRE_PATTERN.search(query)
    if match:
        return AreaOfInterest(region="centre", text=match.group(0))
    return None


def extract_locations(query: str) -> list[str]:
    """Place names as written, in order, without duplicates."""
    places: list[str] = []
    for match in PLACE_PATTERN.finditer(query):
        name = match.group(1).strip()
        # Drop acronyms and vocabulary that only looks like a place.
        words = [
            word.strip("-'")
            for word in name.split()
            if not (word.isupper() and len(word) <= 6)
        ]
        words = [word for word in words if word]
        if not words or words[0].lower() in NOT_PLACES:
            continue
        cleaned = " ".join(words)
        if cleaned not in places:
            places.append(cleaned)
    return places[:5]


# ============================================================
# METRIC AND MODALITY
# ============================================================
METRIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("percentage", re.compile(r"\bpercent(?:age)?\b|%|\bproportion\b|\bshare\b|\bfraction\b", re.I)),
    ("area", re.compile(
        r"\b(?:total|how much)\s+area\b|\barea\s+(?:of|under|covered|affected)\b|"
        r"\bhectares?\b|\bkm2\b|km²|\bsq(?:uare)?\.?\s*(?:km|kilomet)|\bacres?\b", re.I)),
    ("count", re.compile(r"\b(?:how many|count|number of)\b", re.I)),
    ("amount", re.compile(r"\bhow much\b", re.I)),
    ("mean", re.compile(r"\baverage\b|\bmean\b", re.I)),
    ("median", re.compile(r"\bmedian\b", re.I)),
    ("maximum", re.compile(r"\bmaximum\b|\bhighest\b|\bpeak\b", re.I)),
    ("minimum", re.compile(r"\bminimum\b|\blowest\b", re.I)),
]
METRICS = [name for name, _ in METRIC_PATTERNS]

FUSION_PATTERN = re.compile(
    r"\bfus(?:e|ed|ion|ing)\b|\b(?:optical|multispectral)\s+(?:and|with|\+|&)\s+(?:sar|radar)\b|"
    r"\b(?:sar|radar)\s+(?:and|with|\+|&)\s+(?:optical|multispectral)\b|\bboth sensors\b|"
    r"\bcross[- ]?modal\b|\bmulti[- ]?modal\b",
    re.IGNORECASE,
)
SAR_PATTERN = re.compile(
    r"\bsar\b|\bradar\b|backscatter|sentinel[- ]?1\b|polari[sz]ation|\brisat\b", re.IGNORECASE
)
OPTICAL_PATTERN = re.compile(
    r"\boptical\b|\bmultispectral\b|sentinel[- ]?2\b|\blandsat\b|\btrue[- ]colou?r\b|"
    r"\bcartosat\b|\bresourcesat\b|\bliss\b",
    re.IGNORECASE,
)


def extract_metrics(query: str) -> list[str]:
    return [name for name, pattern in METRIC_PATTERNS if pattern.search(query)]


def extract_modality(query: str) -> str | None:
    if FUSION_PATTERN.search(query):
        return "optical+sar"
    if SAR_PATTERN.search(query):
        return "sar"
    if OPTICAL_PATTERN.search(query):
        return "optical"
    return None


def extract_context(query: str) -> QueryContext:
    """Everything a question pins down besides its task."""
    return QueryContext(
        locations=extract_locations(query),
        aoi=extract_aoi(query),
        time_range=extract_time_range(query),
        metrics=extract_metrics(query),
        modality=extract_modality(query),
    )


__all__ = [
    "FUSION_PATTERN",
    "METRICS",
    "OPTICAL_PATTERN",
    "SAR_PATTERN",
    "extract_aoi",
    "extract_context",
    "extract_locations",
    "extract_metrics",
    "extract_modality",
    "extract_periods",
    "extract_time_range",
]
