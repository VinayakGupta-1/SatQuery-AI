from datetime import date
from pydantic import BaseModel, Field


class ImageMetadata(BaseModel):
    acquisition_date: date | None = None
    modality: str | None = None
    sensor: str | None = None
    crs: str | None = None

    width: int | None = None
    height: int | None = None

    bands: list[str] = Field(default_factory=list)

    #: ``[min_x, min_y, max_x, max_y]`` in ``crs``, when georeferenced. Lets
    #: the validator check a question's area against the image's extent.
    bounds: list[float] | None = None


class ImageInput(BaseModel):
    id: str
    path: str
    metadata: ImageMetadata | None = None