"""Resolution of logical band names to concrete bands in a dataset.

The controller speaks in logical terms ("red", "nir") because that is what the
Registry declares as ``required_bands``. Real products name their bands after
the sensor ("B4", "B8", "SR_B5"). This module is the single place that bridges
the two, so no tool has to hard-code a sensor convention.

Band numbering genuinely differs between sensors -- ``B5`` is red-edge on
Sentinel-2 but near-infrared on Landsat-8 -- so resolution is sensor-aware and
refuses to guess when the sensor is unknown and the name is ambiguous.
"""

from __future__ import annotations

import re

from app.tools.raster.model import BandArray, BandResolutionError, RasterDataset

#: Matches a sensor band identifier, with or without zero padding, and with an
#: optional letter suffix. Real Sentinel-2 products name their files "B04" and
#: "B08", while the tables below are keyed "b4" and "b8", so the two forms must
#: be reconciled or no real product would resolve.
BAND_IDENTIFIER = re.compile(r"^b0*(\d{1,2})([a-z]?)$")

# Canonical logical band names used throughout SatQuery.
COASTAL = "coastal"
BLUE = "blue"
GREEN = "green"
RED = "red"
RED_EDGE = "red_edge"
NIR = "nir"
NARROW_NIR = "narrow_nir"
WATER_VAPOUR = "water_vapour"
CIRRUS = "cirrus"
SWIR1 = "swir1"
SWIR2 = "swir2"
PANCHROMATIC = "panchromatic"
THERMAL = "thermal"

# Sensor-specific band identifier -> canonical logical name.
SENTINEL2_BANDS: dict[str, str] = {
    "b1": COASTAL, "b2": BLUE, "b3": GREEN, "b4": RED,
    "b5": RED_EDGE, "b6": RED_EDGE, "b7": RED_EDGE,
    "b8": NIR, "b8a": NARROW_NIR, "b9": WATER_VAPOUR,
    "b10": CIRRUS, "b11": SWIR1, "b12": SWIR2,
}

LANDSAT8_BANDS: dict[str, str] = {
    "b1": COASTAL, "b2": BLUE, "b3": GREEN, "b4": RED, "b5": NIR,
    "b6": SWIR1, "b7": SWIR2, "b8": PANCHROMATIC, "b9": CIRRUS,
    "b10": THERMAL, "b11": THERMAL,
}

LANDSAT7_BANDS: dict[str, str] = {
    "b1": BLUE, "b2": GREEN, "b3": RED, "b4": NIR,
    "b5": SWIR1, "b6": THERMAL, "b7": SWIR2, "b8": PANCHROMATIC,
}

SENSOR_BAND_TABLES: dict[str, dict[str, str]] = {
    "sentinel2": SENTINEL2_BANDS,
    "sentinel-2": SENTINEL2_BANDS,
    "s2": SENTINEL2_BANDS,
    "msi": SENTINEL2_BANDS,
    "landsat8": LANDSAT8_BANDS,
    "landsat-8": LANDSAT8_BANDS,
    "landsat9": LANDSAT8_BANDS,
    "landsat-9": LANDSAT8_BANDS,
    "oli": LANDSAT8_BANDS,
    "landsat7": LANDSAT7_BANDS,
    "landsat-7": LANDSAT7_BANDS,
    "etm+": LANDSAT7_BANDS,
}

# Band numbers whose meaning depends on the sensor. Resolving one of these
# without knowing the sensor would silently compute the wrong index.
AMBIGUOUS_BAND_IDS = {"b5", "b6", "b7", "b9", "b10", "b11"}

# Free-text spellings that map onto a canonical logical name.
LOGICAL_ALIASES: dict[str, str] = {
    "coastal": COASTAL, "aerosol": COASTAL, "coastal_aerosol": COASTAL,
    "blue": BLUE,
    "green": GREEN,
    "red": RED,
    "rededge": RED_EDGE, "red_edge": RED_EDGE, "vegetation_red_edge": RED_EDGE,
    "nir": NIR, "near_infrared": NIR, "nearinfrared": NIR, "infrared": NIR,
    "narrow_nir": NARROW_NIR, "nir_narrow": NARROW_NIR,
    "water_vapour": WATER_VAPOUR, "water_vapor": WATER_VAPOUR,
    "cirrus": CIRRUS,
    "swir": SWIR1, "swir1": SWIR1, "shortwave_infrared": SWIR1,
    "swir2": SWIR2,
    "pan": PANCHROMATIC, "panchromatic": PANCHROMATIC,
    "tir": THERMAL, "thermal": THERMAL,
}


def normalise(name: str) -> str:
    """Reduce a band identifier to a comparable key."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _ambiguous_key(name: str) -> str:
    """Reduce a name to the form compared against :data:`AMBIGUOUS_BAND_IDS`."""
    key = normalise(name)
    match = BAND_IDENTIFIER.match(key)
    return f"b{int(match.group(1))}{match.group(2)}" if match else key


def canonical_name(name: str, sensor: str | None = None) -> str | None:
    """Return the canonical logical name for a band identifier.

    Returns ``None`` when the identifier is a sensor band number whose meaning
    depends on a sensor that was not supplied.
    """
    key = normalise(name)

    if key in LOGICAL_ALIASES:
        return LOGICAL_ALIASES[key]

    # Strip common product prefixes, e.g. Landsat Collection-2 "SR_B5".
    for prefix in ("sr_", "st_", "toa_", "band_", "band"):
        if key.startswith(prefix) and len(key) > len(prefix):
            key = key[len(prefix) :]
            break
    if key.isdigit():
        key = f"b{key}"

    # Reduce "B04"/"B08A" to the "b4"/"b8a" form the tables use.
    match = BAND_IDENTIFIER.match(key)
    if match:
        key = f"b{int(match.group(1))}{match.group(2)}"

    if sensor:
        table = SENSOR_BAND_TABLES.get(normalise(sensor))
        if table and key in table:
            return table[key]

    if key in AMBIGUOUS_BAND_IDS:
        return None
    return SENTINEL2_BANDS.get(key)


def resolve_band(
    dataset: RasterDataset,
    requested: str | int,
    sensor: str | None = None,
) -> BandArray:
    """Resolve ``requested`` to a band of ``dataset``.

    Resolution is attempted in order of decreasing certainty:

    1. an exact (case-insensitive) match on the dataset's band names;
    2. a 1-based band index, whether given as ``2`` or ``"2"``;
    3. a logical match, so ``"red"`` finds the band the sensor calls ``"B4"``.
    """
    if isinstance(requested, int):
        return dataset.band_at(requested)

    text = str(requested).strip()
    if not text:
        raise BandResolutionError("An empty band identifier cannot be resolved.")

    key = normalise(text)
    for band in dataset.bands:
        if normalise(band.name) == key:
            return band

    if text.isdigit():
        return dataset.band_at(int(text))

    sensor = sensor or dataset.metadata.get("sensor")
    wanted = canonical_name(text, sensor)
    if wanted is None:
        # Distinguish "this number means different things on different sensors"
        # from "this is not a band name I know", because the two need different
        # actions from the caller.
        if _ambiguous_key(text) in AMBIGUOUS_BAND_IDS:
            raise BandResolutionError(
                f"Band '{requested}' is ambiguous across sensors and the dataset "
                "does not record which sensor produced it. Supply the sensor in "
                f"metadata, or name the band explicitly. Available bands: "
                f"{dataset.band_names}."
            )
        raise BandResolutionError(
            f"Band '{requested}' is not a recognised band name and is not present "
            f"in the dataset. Available bands: {dataset.band_names}."
        )

    matches = [
        band
        for band in dataset.bands
        if canonical_name(band.name, sensor) == wanted
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise BandResolutionError(
            f"Band '{requested}' matches several bands "
            f"({[band.name for band in matches]}); name one explicitly."
        )

    raise BandResolutionError(
        f"Band '{requested}' (logical name '{wanted}') is not present in the "
        f"dataset. Available bands: {dataset.band_names}."
    )
