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

*Time* -- dates ("2024-08-15", "15/08/2024", "August 15, 2024"), months,
years, Indian seasons ("monsoon 2024", "rabi 2023", "last kharif") and
relative periods ("last month", "past 90 days", "पिछले साल") become a period
the validator then checks every acquisition date against.

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
from datetime import date, timedelta

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
#: Hindi month names, in the spellings people type: with and without the
#: nukta (precomposed or combining), and both common forms of the anusvara.
HINDI_MONTHS = {
    "जनवरी": 1, "फरवरी": 2, "फ़रवरी": 2, "फ़रवरी": 2, "मार्च": 3, "अप्रैल": 4,
    "अप्रेल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9,
    "अक्टूबर": 10, "अक्तूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}
HINDI_MONTH_YEAR_PATTERN = re.compile(
    "(" + "|".join(sorted(HINDI_MONTHS, key=len, reverse=True)) + r")\s*,?\s*" + _YEAR + r"(?!\d)"
)
_MONTH_NAME = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DAY = r"(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
#: "August 15, 2024", "Aug 15th 2024".
MONTH_DAY_YEAR_PATTERN = re.compile(
    r"\b" + _MONTH_NAME + r"\.?\s+" + _DAY + r",?\s+" + _YEAR + r"(?!\d)", re.IGNORECASE
)
#: "15 August 2024", "15th Aug, 2024", "15-Aug-2024".
DAY_MONTH_YEAR_PATTERN = re.compile(
    r"(?<![\d.])" + _DAY + r"[\s-]+(?:of\s+)?" + _MONTH_NAME + r"\.?,?[\s-]+" + _YEAR + r"(?!\d)",
    re.IGNORECASE,
)
#: "15/08/2024", "15-08-2024", "15.08.2024": day first, as dates are written
#: in India, unless the first number cannot be a month and the second can't be
#: a day ("08/15/2024" is then read the American way).
NUMERIC_DATE_PATTERN = re.compile(
    r"(?<![\d./-])(\d{1,2})([/.-])(\d{1,2})\2" + _YEAR + r"(?![\d./-])"
)
#: "2024-08": a whole month, ISO style.
ISO_MONTH_PATTERN = re.compile(r"(?<![\d.])" + _YEAR + r"-(0[1-9]|1[0-2])(?![\d-])")

#: Indian seasons as months ``(first, last)``; a last month smaller than the
#: first runs into the next year (rabi is sown in November and harvested by
#: April). The meteorological seasons follow the India Meteorological
#: Department; the crop seasons are the agricultural calendar.
SEASONS = {
    "winter": (1, 2),
    "pre-monsoon": (3, 5),
    "summer": (3, 5),
    "monsoon": (6, 9),
    "post-monsoon": (10, 12),
    "kharif": (6, 10),
    "rabi": (11, 4),
    "zaid": (3, 6),
}
HINDI_SEASONS = {"मानसून": "monsoon", "मॉनसून": "monsoon", "बरसात": "monsoon", "खरीफ": "kharif",
                 "ख़रीफ़": "kharif", "रबी": "rabi", "सर्दी": "winter", "सर्दियों": "winter",
                 "गर्मी": "summer", "गर्मियों": "summer"}
_SEASON = (
    r"(pre[\s-]?monsoon|post[\s-]?monsoon|monsoon|kharif|rabi|zaid|winter|summer|"
    + "|".join(sorted(HINDI_SEASONS, key=len, reverse=True)) + r")"
)
#: "monsoon 2024", "kharif season of 2023", "2024 monsoon", "मानसून 2024".
SEASON_YEAR_PATTERN = re.compile(
    r"(?<![\w-])" + _SEASON + r"(?:\s+season)?(?:\s+of)?\s*,?\s+" + _YEAR + r"(?!\d)"
    r"|(?<![\d.])" + _YEAR + r"\s+" + _SEASON + r"(?![\w-])",
    re.IGNORECASE,
)
#: "last monsoon", "this kharif", "the monsoon": the latest one that has begun.
#: Winter and summer are left alone without a year or "last"/"this": as bare
#: words they too often describe a crop or a colour, not a period.
SEASON_RELATIVE_PATTERN = re.compile(
    r"(?<![\w-])(?:(last|previous|this|current|recent)\s+)?(?:the\s+)?"
    r"(pre[\s-]?monsoon|post[\s-]?monsoon|monsoon|kharif|rabi|zaid|winter|summer|"
    + "|".join(sorted(HINDI_SEASONS, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE,
)
#: "last month", "past 3 months", "last 90 days", "this year", "पिछले साल".
RELATIVE_PATTERN = re.compile(
    r"\b(?:in\s+)?(?:the\s+)?(last|past|previous|this|current)\s+(?:(\d{1,3})\s+)?"
    r"(days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
HINDI_RELATIVE_PATTERN = re.compile(
    r"(पिछले|पिछला|पिछली|इस)\s+(?:(\d{1,3})\s+)?(साल|सालों|वर्ष|वर्षों|महीने|महीनों|महीना|हफ्ते|हफ़्ते|सप्ताह|दिन|दिनों)"
)
HINDI_UNITS = {"साल": "year", "सालों": "year", "वर्ष": "year", "वर्षों": "year", "महीने": "month",
               "महीनों": "month", "महीना": "month", "हफ्ते": "week", "हफ़्ते": "week",
               "सप्ताह": "week", "दिन": "day", "दिनों": "day"}
OPEN_START = re.compile(r"\b(since|after|from)\s*$", re.IGNORECASE)
OPEN_END = re.compile(r"\b(before|until|till|up to|prior to|by)\s*$", re.IGNORECASE)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _season_span(name: str, year: int) -> tuple[date, date]:
    """The first and last day of a season that begins in ``year``."""
    first, last = SEASONS[name]
    return date(year, first, 1), _month_end(year + (1 if last < first else 0), last)


def _season_key(text: str) -> str:
    text = text.lower()
    if text in HINDI_SEASONS:
        return HINDI_SEASONS[text]
    return re.sub(r"[\s-]+", "-", text)


def _latest_season(name: str, today: date, previous: bool) -> tuple[date, date]:
    """The most recent ``name`` season that has begun; with ``previous``, the
    most recent one that has ended."""
    year = today.year
    span = _season_span(name, year)
    while span[0] > today or (previous and span[1] >= today):
        year -= 1
        span = _season_span(name, year)
    return span


def _relative_span(which: str, count: str | None, unit: str, today: date) -> tuple[date, date] | None:
    """``last month`` -> the previous calendar month; ``last 3 months`` -> the
    three months up to today; ``this year`` -> 1 January to today."""
    unit = unit.lower().rstrip("s")
    which = which.lower()
    if which in {"this", "current", "इस"}:
        if count:
            return None
        if unit == "year":
            return date(today.year, 1, 1), today
        if unit == "month":
            return date(today.year, today.month, 1), today
        if unit == "week":
            return today - timedelta(days=today.weekday()), today
        return today, today
    if count:
        n = int(count)
        if n <= 0:
            return None
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return today - timedelta(days=days), today
    # "last month", "last year": the previous whole calendar period.
    if unit == "year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if unit == "month":
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return date(year, month, 1), _month_end(year, month)
    if unit == "week":
        return today - timedelta(days=7), today
    return today - timedelta(days=1), today - timedelta(days=1)


def _numeric_date(first: int, second: int, year: int) -> date | None:
    """Day-first unless only month-first makes sense."""
    for day, month in ((first, second), (second, first)):
        if 1 <= month <= 12:
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None


def _mentions(query: str, today: date | None = None) -> list[tuple[int, int, date, date]]:
    """Every date-like mention as ``(start, end, first_day, last_day)``.

    Patterns are tried most specific first, and a span already claimed is not
    read again: "15 August 2024" is one day, not also a month and a year.
    """
    today = today or date.today()
    found: list[tuple[int, int, date, date]] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in taken)

    def claim(match: re.Match, first: date, last: date) -> None:
        found.append((match.start(), match.end(), first, last))
        taken.append(match.span())

    for match in ISO_DATE_PATTERN.finditer(query):
        day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        claim(match, day, day)

    for match in NUMERIC_DATE_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        day = _numeric_date(int(match.group(1)), int(match.group(3)), int(match.group(4)))
        if day is not None:
            claim(match, day, day)

    for pattern, day_group, month_group in (
        (MONTH_DAY_YEAR_PATTERN, 2, 1),
        (DAY_MONTH_YEAR_PATTERN, 1, 2),
    ):
        for match in pattern.finditer(query):
            if not free(*match.span()):
                continue
            month = MONTHS[match.group(month_group)[:3].lower()]
            try:
                day = date(int(match.group(3)), month, int(match.group(day_group)))
            except ValueError:
                continue
            claim(match, day, day)

    for match in ISO_MONTH_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        year, month = int(match.group(1)), int(match.group(2))
        claim(match, date(year, month, 1), _month_end(year, month))

    for match in SEASON_YEAR_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        name = match.group(1) or match.group(4)
        year = match.group(2) or match.group(3)
        claim(match, *_season_span(_season_key(name), int(year)))

    for match in MONTH_YEAR_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        month = MONTHS[match.group(1)[:3].lower()]
        year = int(match.group(2))
        last = calendar.monthrange(year, month)[1]
        found.append((match.start(), match.end(), date(year, month, 1), date(year, month, last)))
        taken.append(match.span())

    for match in HINDI_MONTH_YEAR_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        month = HINDI_MONTHS[match.group(1)]
        year = int(match.group(2))
        last = calendar.monthrange(year, month)[1]
        found.append((match.start(), match.end(), date(year, month, 1), date(year, month, last)))
        taken.append(match.span())

    for match in RELATIVE_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        span = _relative_span(match.group(1), match.group(2), match.group(3), today)
        if span is not None:
            claim(match, *span)

    for match in HINDI_RELATIVE_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        span = _relative_span(match.group(1), match.group(2), HINDI_UNITS[match.group(3)], today)
        if span is not None:
            claim(match, *span)

    for match in SEASON_RELATIVE_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        qualifier = (match.group(1) or "").lower()
        name = _season_key(match.group(2))
        if name in {"winter", "summer"} and not qualifier:
            continue
        claim(match, *_latest_season(name, today, previous=qualifier in {"last", "previous"}))

    for match in YEAR_PATTERN.finditer(query):
        if not free(*match.span()):
            continue
        year = int(match.group(1))
        found.append((match.start(), match.end(), date(year, 1, 1), date(year, 12, 31)))
        taken.append(match.span())

    return sorted(found)


def extract_time_range(query: str, today: date | None = None) -> TimeRange | None:
    """The period a question names, or ``None`` when it names none."""
    mentions = _mentions(query, today)
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


def extract_periods(query: str, today: date | None = None) -> list[TimeRange]:
    """Each date, month or year the question names, as its own period, in order.

    :func:`extract_time_range` merges "between 2020 and 2024" into one range,
    which is right for checking acquisition dates. Fetching a before and an
    after image needs the two ends apart: one scene from 2020, one from 2024.
    """
    return [
        TimeRange(start=first, end=last, text=query[start:end])
        for start, end, first, last in _mentions(query, today)
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
    "monsoon", "kharif", "rabi", "zaid", "winter", "summer", "last", "past", "this",
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
        first, second = match.group(1).lower(), (match.group(2) or "").lower()
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


#: A Hindi place name is the word before "में" (in), "के पास" (near),
#: "के आसपास" (around) or "के निकट" (close to).
HINDI_PLACE_PATTERN = re.compile(
    r"([\u0900-\u0963\u0966-\u097F]+)\s+(?:में|के\s+पास|के\s+आसपास|के\s+आस-पास|के\s+निकट)"
)
#: Landforms named by the word before them: झील (lake), नदी (river), बांध
#: (dam), जलाशय (reservoir), घाटी (valley), तट (coast), द्वीप (island),
#: पहाड़ी (hill), सरोवर (lake), वन (forest).
HINDI_LANDFORMS = {"झील", "नदी", "बांध", "बाँध", "जलाशय", "घाटी", "तट", "द्वीप", "पहाड़ी", "सरोवर", "वन"}
HINDI_PREVIOUS_WORD = re.compile(r"([ऀ-ॣ०-ॿ]+)\s+$")
#: Words that sit before those postpositions without being places.
HINDI_NOT_PLACES = {
    "क्षेत्र", "क्षेत्रों", "इलाके", "इलाका", "इलाकों", "छवि", "तस्वीर", "चित्र", "दृश्य",
    "शहर", "जिले", "ज़िले", "राज्य", "बीच", "साल", "वर्ष", "महीने", "दौरान", "इस", "उस",
    "जगह", "भाग", "हिस्से", *HINDI_MONTHS,
}


def extract_locations(query: str) -> list[str]:
    """Place names as written, in order, without duplicates."""
    places: list[str] = []
    for match in HINDI_PLACE_PATTERN.finditer(query):
        name = match.group(1)
        if name in HINDI_LANDFORMS:
            # "चिल्का झील" -- the lake is named by the word before it.
            before = HINDI_PREVIOUS_WORD.search(query[: match.start()])
            if before and before.group(1) not in HINDI_NOT_PLACES:
                name = f"{before.group(1)} {name}"
            else:
                continue
        if name not in HINDI_NOT_PLACES and name not in places:
            places.append(name)
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
    r"\bsar\b|\bradar\b|backscatter|sentinel[- ]?1\b|polari[sz]ation|\brisat\b|रडार", re.IGNORECASE
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


def extract_context(query: str, today: date | None = None) -> QueryContext:
    """Everything a question pins down besides its task."""
    return QueryContext(
        locations=extract_locations(query),
        aoi=extract_aoi(query),
        time_range=extract_time_range(query, today),
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
