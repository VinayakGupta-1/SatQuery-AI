"""Finding scenes in a STAC catalogue: Sentinel-2 L2A and Sentinel-1 RTC.

Both collections come from Microsoft Planetary Computer, which needs no account
and serves every band as a cloud-optimised GeoTIFF, so only the pixels inside
the area of interest are ever downloaded.

*Sentinel-2 L2A* is surface reflectance with a per-pixel scene classification
(SCL) that marks cloud, shadow and cirrus. *Sentinel-1 RTC* is radar
backscatter, radiometrically terrain-corrected gamma-naught in linear power:
calibrated, which is what the SAR tools need, and unaffected by cloud.

A catalogue item is one tile of one satellite pass. An area that straddles two
tiles is covered by two items from the same pass, so items are grouped into
*acquisitions* -- same platform, same day -- and a group is judged by how much
of the area its tiles cover together.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from app.acquisition.web import AcquisitionError, request_json
from app.config.settings import Settings


@dataclass(frozen=True)
class Collection:
    """A catalogue collection and the bands SatQuery reads from it."""

    id: str
    sensor: str
    modality: str
    title: str
    #: ``(asset key, band name written to the file)`` in file order.
    bands: tuple[tuple[str, str], ...]
    #: The asset carrying the cloud classification, if the collection has one.
    cloud_asset: str | None = None
    #: Assets that are class codes rather than measurements: never averaged.
    categorical: tuple[str, ...] = ()

    @property
    def has_clouds(self) -> bool:
        return self.cloud_asset is not None


SENTINEL2 = Collection(
    id="sentinel-2-l2a",
    sensor="sentinel2",
    modality="optical",
    title="Sentinel-2 L2A",
    # Blue, green, red and near-infrared at 10 m, SWIR-1 at 20 m (built-up
    # land and the land-cover rules), and the scene classification.
    bands=(
        ("B02", "B02"),
        ("B03", "B03"),
        ("B04", "B04"),
        ("B08", "B08"),
        ("B11", "B11"),
        ("SCL", "SCL"),
    ),
    cloud_asset="SCL",
    categorical=("SCL",),
)

SENTINEL1 = Collection(
    id="sentinel-1-rtc",
    sensor="sentinel1",
    modality="sar",
    title="Sentinel-1 RTC",
    bands=(("vv", "VV"), ("vh", "VH")),
)


@dataclass
class Item:
    """One catalogue tile of one pass."""

    id: str
    collection: Collection
    acquired: datetime
    geometry: dict[str, Any]
    assets: dict[str, str]
    epsg: int | None
    platform: str | None = None
    cloud_percent: float | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def day(self) -> date:
        return self.acquired.date()


@dataclass
class Acquisition:
    """Tiles of one pass that together cover the area."""

    items: list[Item]
    coverage: float

    @property
    def first(self) -> Item:
        return self.items[0]

    @property
    def day(self) -> date:
        return self.first.day

    @property
    def collection(self) -> Collection:
        return self.first.collection

    @property
    def cloud_percent(self) -> float | None:
        values = [item.cloud_percent for item in self.items if item.cloud_percent is not None]
        return min(values) if values else None


# ============================================================
# COVERAGE
# ============================================================
def _rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    """Outer rings of a GeoJSON Polygon or MultiPolygon."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [coordinates[0]] if coordinates else []
    if kind == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    return []


def _inside(x: float, y: float, ring: list[list[float]]) -> bool:
    """Even-odd point-in-polygon test."""
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index][0], ring[index][1]
        x2, y2 = ring[(index + 1) % count][0], ring[(index + 1) % count][1]
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing:
                inside = not inside
    return inside


def coverage(bbox: list[float], geometries: list[dict[str, Any]], samples: int = 12) -> float:
    """Share of ``bbox`` that falls inside any of ``geometries``.

    Estimated on a ``samples`` x ``samples`` grid of points, which is ample for
    choosing between tiles and needs no geometry library.
    """
    rings = [ring for geometry in geometries for ring in _rings(geometry)]
    if not rings:
        return 0.0
    west, south, east, north = bbox
    hits = 0
    for row in range(samples):
        y = south + (north - south) * (row + 0.5) / samples
        for column in range(samples):
            x = west + (east - west) * (column + 0.5) / samples
            if any(_inside(x, y, ring) for ring in rings):
                hits += 1
    return hits / (samples * samples)


# ============================================================
# SEARCH
# ============================================================
def _parse_datetime(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _epsg(properties: dict[str, Any]) -> int | None:
    code = properties.get("proj:epsg")
    if code is None and isinstance(properties.get("proj:code"), str):
        prefix, _, number = properties["proj:code"].partition(":")
        code = number if prefix.upper() == "EPSG" else None
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _item(feature: dict[str, Any], collection: Collection) -> Item | None:
    properties = feature.get("properties") or {}
    assets = feature.get("assets") or {}
    hrefs = {key: assets[key]["href"] for key, _ in collection.bands if key in assets}
    if len(hrefs) != len(collection.bands) or not properties.get("datetime"):
        return None
    cloud = properties.get("eo:cloud_cover")
    return Item(
        id=str(feature.get("id")),
        collection=collection,
        acquired=_parse_datetime(properties["datetime"]),
        geometry=feature.get("geometry") or {},
        assets=hrefs,
        epsg=_epsg(properties),
        platform=properties.get("platform"),
        cloud_percent=float(cloud) if cloud is not None else None,
        properties=properties,
    )


def search(
    collection: Collection,
    bbox: list[float],
    start: date,
    end: date,
    settings: Settings,
    limit: int = 200,
) -> list[Item]:
    """Every item of ``collection`` touching ``bbox`` between two dates."""
    body: dict[str, Any] = {
        "collections": [collection.id],
        "bbox": bbox,
        "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        "limit": limit,
        "sortby": [{"field": "datetime", "direction": "desc"}],
    }
    if collection.has_clouds:
        body["query"] = {"eo:cloud_cover": {"lte": settings.fetch_max_cloud_percent}}
    response = request_json(
        f"{settings.fetch_stac_url}/search", body=body, timeout=settings.fetch_timeout_seconds
    )
    features = response.get("features") if isinstance(response, dict) else None
    if not isinstance(features, list):
        raise AcquisitionError("The imagery catalogue returned an unexpected answer.")
    items = [_item(feature, collection) for feature in features]
    return [item for item in items if item is not None]


def group_acquisitions(items: list[Item], bbox: list[float]) -> list[Acquisition]:
    """Group tiles by pass and keep the groups that cover most of the area.

    Within a group, tiles are ordered by how much each covers on its own, so
    the mosaic is filled from the best tile first.
    """
    groups: dict[tuple[str | None, date], list[Item]] = {}
    for item in items:
        groups.setdefault((item.platform, item.day), []).append(item)

    acquisitions = []
    for members in groups.values():
        members.sort(key=lambda item: -coverage(bbox, [item.geometry], samples=8))
        acquisitions.append(
            Acquisition(items=members, coverage=coverage(bbox, [m.geometry for m in members]))
        )
    return acquisitions


# ============================================================
# SIGNING
# ============================================================
_tokens: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


def sign(href: str, collection: Collection, settings: Settings) -> str:
    """Append a Planetary Computer read token to an asset URL.

    Tokens are issued anonymously per collection and last about an hour; one is
    reused until five minutes before it expires.
    """
    if not settings.fetch_token_url or "blob.core.windows.net" not in href:
        return href
    with _token_lock:
        cached = _tokens.get(collection.id)
        if cached is None or cached[1] < time.time() + 300:
            response = request_json(
                f"{settings.fetch_token_url}/{collection.id}",
                timeout=settings.fetch_timeout_seconds,
            )
            token = response.get("token") if isinstance(response, dict) else None
            if not token:
                raise AcquisitionError("The imagery provider did not issue a read token.")
            expiry = time.time() + 45 * 60
            if isinstance(response.get("msft:expiry"), str):
                try:
                    expiry = _parse_datetime(response["msft:expiry"]).timestamp()
                except ValueError:
                    pass
            cached = (token, expiry)
            _tokens[collection.id] = cached
    separator = "&" if "?" in href else "?"
    return f"{href}{separator}{cached[0]}"


__all__ = [
    "Acquisition",
    "Collection",
    "Item",
    "SENTINEL1",
    "SENTINEL2",
    "coverage",
    "group_acquisitions",
    "search",
    "sign",
]
