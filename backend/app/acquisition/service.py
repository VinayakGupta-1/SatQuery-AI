"""Fetching the imagery a question needs, when the user supplied none.

The steps, each recorded in the :class:`AcquisitionReport`:

1. **Where.** The location field, coordinates in the question, or the first
   place name in it, geocoded (:mod:`.location`).
2. **What and when.** The sensor, the number of scenes and their date windows,
   from the understood task (:mod:`.planner`).
3. **Which scene.** Every pass over the area in the window is found and
   ranked: full coverage first, then the catalogue's cloud estimate, then --
   for a before image -- the same season as the after image, then the most
   recent. The catalogue's cloud figure describes a 110 km tile, so the
   leading optical candidates are then checked on the downloaded SCL band for
   the area itself, and the clearest is kept.
4. **Download.** Only the area's pixels, onto one grid shared by every scene
   of the question (:mod:`.reader`).
5. **Harmonise.** Sentinel-2 processing baseline 04.00 and later store
   reflectance with a +1000 offset (``BOA_ADD_OFFSET``). It is removed here so
   every index tool, whose default offset is 0, computes the right value.
6. **Write** one self-describing GeoTIFF per scene: band names, sensor,
   modality and acquisition date are tags in the file, so the validator reads
   them from the file exactly as it does for an upload.

The files then enter the pipeline like uploads and are validated like uploads.
Nothing about fetched imagery is trusted more.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from app.acquisition import reader
from app.acquisition.catalog import (
    SENTINEL1,
    Acquisition,
    Collection,
    Item,
    group_acquisitions,
    search,
    sign,
)
from app.acquisition.location import ResolvedArea, resolve_area
from app.acquisition.planner import AcquisitionPlan, SceneRequest, plan_acquisition
from app.acquisition.web import AcquisitionError
from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings
from app.controller.input_requirements.input_requirements import FUSION_MAX_DAYS
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult
from app.schemas.acquisition import AcquiredScene, AcquisitionReport
from app.tools.raster.backends import has_rasterio
from app.tools.raster.io import write_raster
from app.tools.raster.model import BandArray, GeoReference

logger = get_logger("acquisition")

#: A pass must cover at least this share of the area to be considered at all,
#: and is preferred when it covers this much.
MIN_COVERAGE = 0.5
FULL_COVERAGE = 0.95

#: SCL classes counted as cloud over the area: shadow, medium and high
#: probability cloud, thin cirrus.
SCL_CLOUD = (3, 8, 9, 10)
#: An optical candidate this clear over the area is accepted without looking
#: at the next one.
CLEAR_ENOUGH = 0.10
#: How many optical candidates may be checked on their own SCL band.
MAX_CLOUD_CHECKS = 4

#: Where step-by-step progress goes during one ``acquire`` call, if anywhere.
_progress: ContextVar[Callable[[str], None] | None] = ContextVar("acquisition_progress", default=None)


def _say(message: str) -> None:
    report = _progress.get()
    if report is not None:
        try:
            report(message)
        except Exception:  # progress is a courtesy; it never breaks a fetch
            pass


#: Sentinel-2 processing baselines from this one on store reflectance + 1000.
OFFSET_BASELINE = 4.0
BOA_ADD_OFFSET = 1000


@dataclass
class FetchedImage:
    """A scene written to disk, ready to be described like an upload."""

    path: str
    display_name: str
    scene: AcquiredScene


@dataclass
class AcquisitionOutcome:
    images: list[FetchedImage] = field(default_factory=list)
    report: AcquisitionReport = field(
        default_factory=lambda: AcquisitionReport(status="failed")
    )


# ============================================================
# RANKING
# ============================================================
def _cloud_bucket(percent: float | None) -> int:
    """Coarse cloud classes, so a 3 % scene is not preferred over a 1 % one
    from three weeks later."""
    if percent is None or percent <= 5:
        return 0
    if percent <= 20:
        return 1
    if percent <= 50:
        return 2
    return 3


def _season_distance(day: date, target: date) -> int:
    """Days between two dates' positions in the year, ignoring the year."""
    gap = abs(day.timetuple().tm_yday - target.timetuple().tm_yday)
    return min(gap, 365 - gap)


def rank(
    acquisitions: list[Acquisition],
    season_of: date | None = None,
) -> list[Acquisition]:
    """Best first: coverage, cloud, season (when matching one), recency."""
    eligible = [a for a in acquisitions if a.coverage >= MIN_COVERAGE]
    return sorted(
        eligible,
        key=lambda a: (
            0 if a.coverage >= FULL_COVERAGE else 1,
            _cloud_bucket(a.cloud_percent),
            _season_distance(a.day, season_of) if season_of else 0,
            -a.day.toordinal(),
        ),
    )


# ============================================================
# READING
# ============================================================
def utm_epsg(lon: float, lat: float) -> int:
    """The WGS 84 / UTM zone code for a point, which every grid is built in."""
    zone = min(int((lon + 180) // 6) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone


def _nodata(collection: Collection) -> float:
    return float("nan") if collection is SENTINEL1 else 0.0


def _offset(item: Item) -> int:
    """The additive offset this item's reflectance carries."""
    baseline = item.properties.get("s2:processing_baseline")
    try:
        return BOA_ADD_OFFSET if baseline is not None and float(baseline) >= OFFSET_BASELINE else 0
    except (TypeError, ValueError):
        return 0


def _harmonise(values: Any, item: Item, key: str) -> Any:
    """Remove the reflectance offset, keeping 0 as nodata."""
    import numpy

    offset = _offset(item)
    if not offset or key in item.collection.categorical:
        return values
    shifted = numpy.clip(values.astype(numpy.int32) - offset, 1, 65535)
    return numpy.where(values == 0, 0, shifted).astype(values.dtype)


def _missing(values: Any, nodata: float) -> Any:
    import numpy

    return numpy.isnan(values) if nodata != nodata else values == nodata


def read_band(acquisition: Acquisition, key: str, grid: reader.Grid, settings: Settings) -> Any:
    """One band of a pass on ``grid``, mosaicked from its tiles best first."""
    collection = acquisition.collection
    nodata = _nodata(collection)
    mosaic = None
    for item in acquisition.items:
        values = reader.read_asset(
            sign(item.assets[key], collection, settings),
            grid,
            categorical=key in collection.categorical,
            nodata=nodata,
        )
        values = _harmonise(values, item, key)
        if mosaic is None:
            mosaic = values
        else:
            gaps = _missing(mosaic, nodata)
            mosaic[gaps] = values[gaps]
        if not _missing(mosaic, nodata).any():
            break
    return mosaic


def cloud_and_coverage(scl: Any) -> tuple[float, float]:
    """``(cloud fraction of the covered pixels, covered fraction)`` from SCL."""
    import numpy

    covered = scl != 0
    count = int(covered.sum())
    if count == 0:
        return 1.0, 0.0
    cloudy = int((numpy.isin(scl, SCL_CLOUD) & covered).sum())
    return cloudy / count, count / scl.size


# ============================================================
# SELECTION
# ============================================================
@dataclass
class _Choice:
    acquisition: Acquisition
    bands: dict[str, Any] = field(default_factory=dict)
    cloud: float | None = None
    coverage: float | None = None


def _candidates(request: SceneRequest, area: ResolvedArea, settings: Settings) -> list[Acquisition]:
    _say(
        f"Searching {request.collection.title} scenes from "
        f"{request.start.isoformat()} to {request.end.isoformat()}"
    )
    items = search(request.collection, area.bbox, request.start, request.end, settings)
    return group_acquisitions(items, area.bbox)


def _unavailable(request: SceneRequest, area: ResolvedArea, settings: Settings) -> AcquisitionError:
    collection = request.collection
    detail = (
        f" with at most {settings.fetch_max_cloud_percent} % cloud"
        if collection.has_clouds
        else ""
    )
    lag = (
        " Sentinel-1 RTC scenes reach the catalogue about two weeks after they are acquired."
        if collection is SENTINEL1
        else ""
    )
    return AcquisitionError(
        f"No {collection.title} scene{detail} covers {area.name} between "
        f"{request.start.isoformat()} and {request.end.isoformat()}.{lag} Try a "
        "longer period (for example 'in 2025'), another place, or attach imagery.",
        status="unavailable",
    )


def _choose(
    ranked: list[Acquisition],
    grid: reader.Grid,
    settings: Settings,
) -> _Choice:
    """The first ranked pass, or for optical imagery the clearest of the leaders.

    Each optical candidate's SCL band is downloaded for the area -- a small
    read -- and the first that is clear enough is taken. When none is, the
    clearest seen wins and the report says how cloudy it was.
    """
    first = ranked[0]
    collection = first.collection
    if not collection.has_clouds:
        return _Choice(first)

    best: _Choice | None = None
    for acquisition in ranked[:MAX_CLOUD_CHECKS]:
        _say(f"Checking cloud over the area on the {acquisition.day.isoformat()} scene")
        scl = read_band(acquisition, collection.cloud_asset, grid, settings)
        cloud, covered = cloud_and_coverage(scl)
        choice = _Choice(acquisition, {collection.cloud_asset: scl}, cloud, covered)
        if best is None or (cloud + (1 - covered)) < (best.cloud + (1 - best.coverage)):
            best = choice
        if cloud <= CLEAR_ENOUGH and covered >= FULL_COVERAGE:
            break
    return best


def _download(
    choice: _Choice, keys: tuple[str, ...], grid: reader.Grid, settings: Settings
) -> dict[str, Any]:
    """The requested bands of the chosen pass, read in parallel."""
    remaining = [key for key in keys if key not in choice.bands]
    with ThreadPoolExecutor(max_workers=max(len(remaining), 1)) as pool:
        results = pool.map(
            lambda key: (key, read_band(choice.acquisition, key, grid, settings)), remaining
        )
        bands = dict(choice.bands)
        bands.update(dict(results))
    return bands


def _write(
    choice: _Choice,
    keys: tuple[str, ...],
    bands: dict[str, Any],
    grid: reader.Grid,
    role: str,
    image_id: str,
    directory: str,
) -> FetchedImage:
    acquisition = choice.acquisition
    collection = acquisition.collection
    nodata = _nodata(collection)
    dtype = "float32" if collection is SENTINEL1 else "uint16"
    names = dict(collection.bands)
    arrays = [
        BandArray(
            name=names[key],
            width=grid.width,
            height=grid.height,
            values=bands[key].astype(dtype).reshape(-1),
            dtype=dtype,
            nodata=nodata,
        )
        for key in keys
    ]
    day = acquisition.day.isoformat()
    path = os.path.join(directory, f"{image_id}_{collection.sensor}_{day}.tif")
    item_ids = [item.id for item in acquisition.items]
    write_raster(
        path,
        arrays,
        GeoReference(crs=grid.crs, transform=grid.transform),
        dtype=dtype,
        nodata=nodata,
        compress="deflate" if has_rasterio() else None,
        metadata={
            "sensor": collection.sensor,
            "modality": collection.modality,
            "ACQUISITION_DATE": day,
            "platform": acquisition.first.platform,
            "source": "Microsoft Planetary Computer",
            "collection": collection.id,
            "stac_items": ",".join(item_ids),
            "reflectance_offset_removed": (
                str(BOA_ADD_OFFSET) if any(_offset(item) for item in acquisition.items) else None
            ),
        },
    )

    if choice.coverage is None:
        import numpy

        first = bands[keys[0]]
        covered = ~_missing(first, nodata)
        choice.coverage = float(numpy.count_nonzero(covered)) / first.size

    scene = AcquiredScene(
        image_id=image_id,
        role=role,
        collection=collection.id,
        sensor=collection.sensor,
        modality=collection.modality,
        platform=acquisition.first.platform,
        item_ids=item_ids,
        acquired=day,
        tile_cloud_percent=acquisition.cloud_percent,
        area_cloud_fraction=choice.cloud,
        coverage=round(choice.coverage, 4),
        resolution_m=grid.resolution,
        bands=[names[key] for key in keys],
    )
    label = f"{collection.title} · {day}"
    if role != "image":
        label += f" ({role})"
    return FetchedImage(path=path, display_name=label, scene=scene)


# ============================================================
# ENTRY POINT
# ============================================================
def _select(
    plan: AcquisitionPlan,
    area: ResolvedArea,
    grid: reader.Grid,
    settings: Settings,
) -> list[tuple[SceneRequest, _Choice]]:
    """Choose a pass for every request in the plan."""
    if plan.kind == "fusion":
        optical_request, sar_request = plan.requests
        optical = rank(_candidates(optical_request, area, settings))
        if not optical:
            raise _unavailable(optical_request, area, settings)
        radar = [a for a in _candidates(sar_request, area, settings) if a.coverage >= MIN_COVERAGE]
        # Only optical scenes with a radar partner close enough to fuse.
        paired = []
        for candidate in optical:
            near = [
                a for a in radar
                if abs((a.day - candidate.day).days) <= FUSION_MAX_DAYS
            ]
            if near:
                near.sort(key=lambda a: (abs((a.day - candidate.day).days), -a.coverage))
                paired.append((candidate, near[0]))
        if not paired:
            raise AcquisitionError(
                f"No Sentinel-1 scene of {area.name} was acquired within "
                f"{FUSION_MAX_DAYS} days of a usable Sentinel-2 scene between "
                f"{optical_request.start.isoformat()} and {optical_request.end.isoformat()}. "
                "Sentinel-1 RTC scenes reach the catalogue about two weeks after "
                "acquisition; try an earlier period.",
                status="unavailable",
            )
        partners = {id(o): s for o, s in paired}
        chosen_optical = _choose([o for o, _ in paired], grid, settings)
        return [
            (optical_request, chosen_optical),
            (sar_request, _Choice(partners[id(chosen_optical.acquisition)])),
        ]

    if plan.kind == "change":
        before_request, after_request = plan.requests
        after_ranked = rank(_candidates(after_request, area, settings))
        if not after_ranked:
            raise _unavailable(after_request, area, settings)
        after = _choose(after_ranked, grid, settings)
        before_pool = [
            a for a in _candidates(before_request, area, settings)
            if (after.acquisition.day - a.day).days >= 1
        ]
        # The same season as the after scene: phenology would otherwise read
        # as change.
        before_ranked = rank(before_pool, season_of=after.acquisition.day)
        if not before_ranked:
            raise _unavailable(before_request, area, settings)
        return [(before_request, _choose(before_ranked, grid, settings)), (after_request, after)]

    (request,) = plan.requests
    ranked = rank(_candidates(request, area, settings))
    if not ranked:
        raise _unavailable(request, area, settings)
    return [(request, _choose(ranked, grid, settings))]


def acquire(
    understanding: TaskUnderstandingResult,
    location: str | None,
    directory: str,
    settings: Settings | None = None,
    today: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> AcquisitionOutcome:
    """Find, download and write the imagery a question needs.

    Never raises for an expected failure: an unresolvable place, an empty
    catalogue or an unreachable provider becomes a report whose status and
    message say so, which the pipeline turns into the answer.
    """
    settings = settings or get_settings()
    today = today or datetime.now(timezone.utc).date()
    token = _progress.set(progress)
    try:
        return _acquire(understanding, location, directory, settings, today)
    finally:
        _progress.reset(token)


def _acquire(
    understanding: TaskUnderstandingResult,
    location: str | None,
    directory: str,
    settings: Settings,
    today: date,
) -> AcquisitionOutcome:
    report = AcquisitionReport(status="failed")
    try:
        if not settings.fetch_enabled:
            raise AcquisitionError(
                "No imagery was attached, and automatic imagery fetching is turned off "
                "on this server (SATQUERY_FETCH_ENABLED). Attach a GeoTIFF to analyse it."
            )
        _say("Finding the place")
        area = resolve_area(location, understanding.original_query, understanding.context, settings)
        _say(f"Found {area.name.split(',')[0]}")
        report.place, report.place_source, report.bbox_lonlat = area.name, area.source, area.bbox
        report.notes.extend(area.notes)

        plan = plan_acquisition(understanding, settings, today)
        report.period = plan.period
        report.notes.extend(plan.notes)

        grid = reader.make_grid(area.bbox, utm_epsg(*area.centre), settings)
        os.makedirs(directory, exist_ok=True)
        images = []
        for index, (request, choice) in enumerate(_select(plan, area, grid, settings), start=1):
            _say(
                f"Downloading {len(request.assets)} bands of the "
                f"{choice.acquisition.day.isoformat()} {choice.acquisition.collection.title} scene"
            )
            bands = _download(choice, request.assets, grid, settings)
            images.append(
                _write(choice, request.assets, bands, grid, request.role, f"image_{index}", directory)
            )
    except AcquisitionError as error:
        report.status = error.status  # type: ignore[assignment]
        report.message = str(error)
        logger.info("imagery not acquired", extra={"status": error.status, "reason": str(error)})
        return AcquisitionOutcome(report=report)

    report.status = "fetched"
    report.scenes = [image.scene for image in images]
    for image in images:
        scene = image.scene
        if scene.area_cloud_fraction is not None and scene.area_cloud_fraction > CLEAR_ENOUGH:
            report.notes.append(
                f"The clearest {scene.role} scene found was still "
                f"{scene.area_cloud_fraction:.0%} cloud over the area; cloudy pixels "
                "are excluded from measurements using its SCL band."
            )
        if scene.coverage < FULL_COVERAGE:
            report.notes.append(
                f"The {scene.role} scene covers {scene.coverage:.0%} of the area; the "
                "rest is nodata."
            )
    report.message = (
        f"Fetched {len(images)} scene{'s' if len(images) != 1 else ''} of {area.name}: "
        + "; ".join(f"{image.scene.collection} from {image.scene.acquired}" for image in images)
        + "."
    )
    logger.info(
        "imagery acquired",
        extra={"place": area.name, "scenes": [image.scene.item_ids for image in images]},
    )
    return AcquisitionOutcome(images=images, report=report)


__all__ = [
    "AcquisitionOutcome",
    "FetchedImage",
    "acquire",
    "cloud_and_coverage",
    "rank",
    "utm_epsg",
]
