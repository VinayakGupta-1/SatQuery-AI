"""Where and when a question is about.

These are read from the sentence by the understanding stage and then enforced
deterministically: a time range becomes a validator check on acquisition
dates, and an area of interest becomes a clip applied before any arithmetic.
They are shared schemas rather than controller models because the validator
and the API use them too.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

#: Named parts of a scene, as fractions of its extent: (left, top, right,
#: bottom), with the top of the image to the north.
REGION_FRACTIONS: dict[str, tuple[float, float, float, float]] = {
    "north": (0.0, 0.0, 1.0, 0.5),
    "south": (0.0, 0.5, 1.0, 1.0),
    "west": (0.0, 0.0, 0.5, 1.0),
    "east": (0.5, 0.0, 1.0, 1.0),
    "north_west": (0.0, 0.0, 0.5, 0.5),
    "north_east": (0.5, 0.0, 1.0, 0.5),
    "south_west": (0.0, 0.5, 0.5, 1.0),
    "south_east": (0.5, 0.5, 1.0, 1.0),
    "centre": (0.25, 0.25, 0.75, 0.75),
}


class TimeRange(BaseModel):
    """A period the question names. Either end may be open."""

    start: date | None = None
    end: date | None = None
    #: The words it was read from, for the audit trail.
    text: str = ""

    def contains(self, day: date) -> bool:
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day > self.end:
            return False
        return True

    def describe(self) -> str:
        if self.start and self.end:
            return f"{self.start.isoformat()} to {self.end.isoformat()}"
        if self.start:
            return f"from {self.start.isoformat()}"
        if self.end:
            return f"until {self.end.isoformat()}"
        return "any time"


class AreaOfInterest(BaseModel):
    """The part of the ground a question is about.

    Exactly one of ``bbox`` and ``region`` is set. ``bbox`` is
    ``[min_x, min_y, max_x, max_y]`` in ``crs`` -- longitude and latitude by
    default. ``region`` names a part of the scene itself ("north_west").
    """

    bbox: list[float] | None = None
    crs: str = "EPSG:4326"
    region: str | None = None
    text: str = ""

    def describe(self) -> str:
        if self.region:
            return f"the {self.region.replace('_', '-')} of the scene"
        if self.bbox:
            min_x, min_y, max_x, max_y = self.bbox
            if self.crs.upper() == "EPSG:4326":
                return (
                    f"longitude {min_x:.4f} to {max_x:.4f}, "
                    f"latitude {min_y:.4f} to {max_y:.4f}"
                )
            return f"{min_x:g}, {min_y:g} to {max_x:g}, {max_y:g} ({self.crs})"
        return "the whole scene"


class QueryContext(BaseModel):
    """Everything besides the task that a question pins down."""

    #: Place names as written. Not geocoded: SatQuery reports them, and the
    #: footprint of the imagery, so the user can check they match.
    locations: list[str] = Field(default_factory=list)
    aoi: AreaOfInterest | None = None
    time_range: TimeRange | None = None
    #: What the answer should lead with: area, percentage, mean, count ...
    metrics: list[str] = Field(default_factory=list)
    #: What the sentence says about the sensor: optical, sar or optical+sar.
    modality: str | None = None


__all__ = ["AreaOfInterest", "QueryContext", "REGION_FRACTIONS", "TimeRange"]
