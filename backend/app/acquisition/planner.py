"""Deciding which scenes a question needs, before any is searched for.

The understood task fixes the sensor and the number of images; the question's
dates fix the windows they are drawn from:

* Most questions need **one optical scene** (Sentinel-2): vegetation, water,
  built-up land, land cover, objects, questions for the vision model.
* Flooding is mapped on **radar** (Sentinel-1) unless the question asks for
  optical imagery: floods come with cloud, and radar sees through it. So is any
  question that names SAR or radar.
* A change question needs **a before and an after scene** from the same
  sensor, put on the same grid.
* A question for both sensors needs **an optical and a radar scene** acquired
  close enough together to show the same ground on the same day or so.

Every window lies inside the period the question names, so the validator's
acquisition-date check -- which still runs on the fetched files -- passes for
the right reason rather than being bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.acquisition.catalog import SENTINEL1, SENTINEL2, Collection
from app.acquisition.web import AcquisitionError
from app.config.settings import Settings
from app.controller.input_requirements.input_requirements import (
    FUSION_MAX_DAYS,
    change_index_for,
)
from app.controller.task_understanding.context import extract_periods
from app.controller.task_understanding.task_understanding import TaskUnderstandingResult
from app.schemas.spatiotemporal import TimeRange

CHANGE_TASKS = {"change_detection", "change_vqa"}

#: The Sentinel-2 L2A archive is global from about this date.
SENTINEL2_ARCHIVE_START = date(2017, 1, 1)
#: Sentinel-1 RTC on Planetary Computer starts with the first Sentinel-1 data.
SENTINEL1_ARCHIVE_START = date(2014, 10, 1)


#: Tasks that never read SWIR. Every other optical task gets B11, so a task the
#: rules do not recognise still has every band a tool might ask for.
NO_SWIR_TASKS = {
    "ndvi", "ndwi", "flood_mapping", "image_analysis", "image_captioning",
    "change_vqa", "optical_sar_fusion",
}


@dataclass
class SceneRequest:
    """One scene to find: what it is for, from which collection, and when."""

    role: str
    collection: Collection
    start: date
    end: date
    #: Asset keys to download, in the collection's band order. Downloading is
    #: the slow part, so a band no tool will read is not fetched.
    assets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.assets:
            self.assets = tuple(key for key, _ in self.collection.bands)

    def describe(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


def optical_assets(understanding: TaskUnderstandingResult) -> tuple[str, ...]:
    """The Sentinel-2 bands a task needs.

    True colour and near-infrared always: every index uses NIR, and the
    preview, the vision model and the map overlay are drawn from red, green
    and blue. SCL always, for the cloud mask. SWIR-1 only when a tool reads it.
    """
    task = understanding.task_type
    swir = task not in NO_SWIR_TASKS
    if task in CHANGE_TASKS:
        swir = change_index_for(understanding) == "ndbi"
    wanted = {"B02", "B03", "B04", "B08", "SCL"} | ({"B11"} if swir else set())
    return tuple(key for key, _ in SENTINEL2.bands if key in wanted)


@dataclass
class AcquisitionPlan:
    """``single``, ``change`` (before, after) or ``fusion`` (optical, sar)."""

    kind: str
    requests: list[SceneRequest]
    notes: list[str] = field(default_factory=list)

    @property
    def period(self) -> str:
        if len(self.requests) == 1:
            return self.requests[0].describe()
        return "; ".join(f"{request.role}: {request.describe()}" for request in self.requests)


def choose_sensor(understanding: TaskUnderstandingResult) -> str:
    """``optical``, ``sar`` or ``fusion`` for a question."""
    task = understanding.task_type
    modality = understanding.context.modality
    if task == "optical_sar_fusion" or modality == "optical+sar":
        return "fusion"
    if task == "sar_analysis" or modality == "sar":
        return "sar"
    if task == "flood_mapping" and modality != "optical":
        return "sar"
    return "optical"


def _archive_start(collection: Collection) -> date:
    return SENTINEL1_ARCHIVE_START if collection is SENTINEL1 else SENTINEL2_ARCHIVE_START


def _bounded(
    collection: Collection,
    role: str,
    start: date,
    end: date,
    today: date,
    assets: tuple[str, ...] = (),
) -> SceneRequest:
    """A request with its window clipped to what the archive can hold."""
    end = min(end, today)
    start = max(start, _archive_start(collection))
    if start > today:
        raise AcquisitionError(
            f"The period asked about starts on {start.isoformat()}, which is in the "
            "future, so no imagery exists for it yet.",
            status="unavailable",
        )
    if end < start:
        raise AcquisitionError(
            f"{collection.title} imagery is archived from "
            f"{_archive_start(collection).isoformat()}; the period asked about ends "
            f"before that. Attach older imagery to analyse it.",
            status="unavailable",
        )
    return SceneRequest(role=role, collection=collection, start=start, end=end, assets=assets)


def _window(period: TimeRange | None, today: date, lookback: timedelta) -> tuple[date, date]:
    """The search window for one period; the recent past when there is none."""
    if period is None:
        return today - lookback, today
    end = period.end or today
    start = period.start or (end - lookback)
    return start, end


def plan_acquisition(
    understanding: TaskUnderstandingResult,
    settings: Settings,
    today: date,
) -> AcquisitionPlan:
    """The scenes a question needs and the windows to look for them in."""
    lookback = timedelta(days=max(settings.fetch_lookback_days, 1))
    sensor = choose_sensor(understanding)
    time_range = understanding.context.time_range
    notes: list[str] = []

    if sensor == "fusion":
        start, end = _window(time_range, today, lookback)
        return AcquisitionPlan(
            kind="fusion",
            requests=[
                _bounded(SENTINEL2, "optical", start, end, today, optical_assets(understanding)),
                # The radar window reaches past the optical one on both sides so
                # a partner can be found for a scene at either edge of it.
                _bounded(
                    SENTINEL1, "sar",
                    start - timedelta(days=FUSION_MAX_DAYS), end + timedelta(days=FUSION_MAX_DAYS),
                    today,
                ),
            ],
        )

    collection = SENTINEL1 if sensor == "sar" else SENTINEL2
    assets = optical_assets(understanding) if collection is SENTINEL2 else ()
    if sensor == "sar" and understanding.task_type == "flood_mapping":
        notes.append(
            "Flooding was mapped on Sentinel-1 radar, which sees through the cloud "
            "that usually comes with a flood. Ask for optical imagery to use "
            "Sentinel-2 instead."
        )

    if understanding.task_type not in CHANGE_TASKS:
        start, end = _window(time_range, today, lookback)
        return AcquisitionPlan(
            kind="single",
            requests=[_bounded(collection, "image", start, end, today, assets)],
            notes=notes,
        )

    periods = extract_periods(understanding.original_query)
    year = timedelta(days=365)
    if len(periods) >= 2:
        before = _window(periods[0], today, lookback)
        after = _window(periods[-1], today, lookback)
        if before[0] > after[0]:
            before, after = after, before
    elif time_range is not None and time_range.start is not None and time_range.end is None:
        # "since 2020": a scene from 2020 against a recent one.
        before = _window(periods[0] if periods else time_range, today, lookback)
        after = _window(None, today, lookback)
    elif time_range is not None and time_range.start is None and time_range.end is not None:
        # "before 2020": both scenes must predate the end; a year apart.
        after = (time_range.end - lookback, time_range.end)
        before = (after[0] - year, after[1] - year)
    elif time_range is not None and time_range.start is not None and time_range.end is not None:
        # "during 2024": both scenes must fall inside it; early against late.
        middle = time_range.start + (min(time_range.end, today) - time_range.start) / 2
        before = (time_range.start, middle)
        after = (middle + timedelta(days=1), time_range.end)
    else:
        after = _window(None, today, lookback)
        before = (after[0] - year, after[1] - year)
        notes.append(
            "No dates were given, so the most recent clear scene was compared with "
            "one from the same season a year earlier."
        )

    return AcquisitionPlan(
        kind="change",
        requests=[
            _bounded(collection, "before", before[0], before[1], today, assets),
            _bounded(collection, "after", after[0], after[1], today, assets),
        ],
        notes=notes,
    )


__all__ = [
    "AcquisitionPlan",
    "CHANGE_TASKS",
    "SceneRequest",
    "choose_sensor",
    "plan_acquisition",
]
