"""What automatic imagery acquisition did, for the audit trail and the API.

When a user asks a question without uploading imagery, SatQuery finds a scene
itself. Which place it searched, which period, which scene it picked and why
are as much a part of the answer as the tool's statistics: an NDVI figure means
nothing until the reader knows it describes Pune on 12 February, from a
Sentinel-2 scene that was 0.2 % cloud.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: ``fetched``        -- every scene the task needs was downloaded.
#: ``needs_location`` -- the question names no place SatQuery could resolve.
#: ``unavailable``    -- the catalogue holds no usable scene for the place and period.
#: ``failed``         -- the catalogue or the download could not be reached.
AcquisitionStatus = Literal["fetched", "needs_location", "unavailable", "failed"]


class AcquiredScene(BaseModel):
    """One image SatQuery downloaded, and where it came from."""

    image_id: str
    #: What the image is for: ``image``, ``before``, ``after``, ``optical`` or ``sar``.
    role: str
    collection: str
    sensor: str
    modality: str
    platform: str | None = None
    #: Catalogue item ids. More than one when adjacent tiles of the same pass
    #: were mosaicked to cover the area.
    item_ids: list[str] = Field(default_factory=list)
    acquired: str
    #: Cloud cover of the whole catalogue tile, in percent, as the provider reports it.
    tile_cloud_percent: float | None = None
    #: Share of the area's pixels the scene's own SCL band calls cloud, shadow
    #: or cirrus. Measured on the downloaded pixels, not taken from the catalogue.
    area_cloud_fraction: float | None = None
    #: Share of the area the scene has data for.
    coverage: float = 1.0
    resolution_m: float
    #: Bands written to the file, in order.
    bands: list[str] = Field(default_factory=list)


class AcquisitionReport(BaseModel):
    """How the imagery for a question was found, or why it could not be."""

    status: AcquisitionStatus
    message: str = ""
    #: The place as resolved: a geocoder's full name, or the coordinates.
    place: str | None = None
    #: ``location field``, ``query coordinates`` or ``geocoded``.
    place_source: str | None = None
    #: The area actually downloaded, ``[west, south, east, north]`` in degrees.
    bbox_lonlat: list[float] | None = None
    #: The period searched, in words.
    period: str | None = None
    provider: str = "Microsoft Planetary Computer"
    attribution: str = (
        "Contains modified Copernicus Sentinel data, processed by ESA; "
        "accessed through Microsoft Planetary Computer. Place names "
        "© OpenStreetMap contributors."
    )
    scenes: list[AcquiredScene] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == "fetched"


__all__ = ["AcquiredScene", "AcquisitionReport", "AcquisitionStatus"]
