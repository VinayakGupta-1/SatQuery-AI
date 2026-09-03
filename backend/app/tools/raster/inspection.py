"""Derive :class:`ImageMetadata` from an actual raster file.

Until now the controller was handed metadata that a caller wrote by hand. A
real upload arrives as bytes, so something has to read the file and describe
it before the validator can check anything.

The rule here is that a property is reported only when the file actually
carries it. An absent CRS stays ``None`` rather than defaulting to WGS84, and
an undeterminable modality stays ``None`` rather than being guessed as
optical -- the validator is then free to reject the input, which is the
correct outcome. Guessing here would defeat the entire validation layer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.schemas.inputs import ImageMetadata
from app.tools.raster.bands import canonical_name, normalise
from app.tools.raster.io import open_raster
from app.tools.raster.model import RasterDataset

#: Polarisation channels that identify a SAR product.
SAR_POLARISATIONS = {"vv", "vh", "hh", "hv"}

#: TIFF/GDAL tags that may carry an acquisition timestamp.
DATE_TAGS = ("ACQUISITION_DATE", "TIFFTAG_DATETIME", "DATETIME")

DATE_FORMATS = (
    "%Y:%m:%d %H:%M:%S",  # the TIFF DateTime convention
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y%m%d",
)


def infer_modality(dataset: RasterDataset) -> str | None:
    """Infer whether a dataset is optical or SAR from its band names.

    Returns ``None`` when the bands support neither conclusion, so the caller
    can require the modality to be stated rather than assumed.
    """
    declared = dataset.metadata.get("modality")
    if isinstance(declared, str) and declared.strip():
        return declared.strip().lower()

    names = {normalise(name) for name in dataset.band_names}
    if names & SAR_POLARISATIONS:
        return "sar"

    sensor = dataset.metadata.get("sensor")
    if any(canonical_name(name, sensor) for name in dataset.band_names):
        return "optical"
    return None


def logical_band_names(dataset: RasterDataset) -> list[str]:
    """Return each band's logical name, keeping the raw name when unmapped.

    The controller and validator reason in logical terms ("red", "nir"), so
    this is the form they need. A band whose meaning cannot be established is
    passed through under its own name rather than being dropped, which keeps
    the validator's report honest about what the file contains.
    """
    sensor = dataset.metadata.get("sensor")
    names: list[str] = []
    for raw in dataset.band_names:
        logical = canonical_name(raw, sensor)
        candidate = logical or raw
        if candidate not in names:
            names.append(candidate)
    return names


def parse_acquisition_date(value: Any) -> date | None:
    """Parse an acquisition date from a tag value, or return ``None``."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def find_acquisition_date(dataset: RasterDataset) -> date | None:
    """Look for an acquisition date among the dataset's tags and sidecar."""
    for key in ("acquisition_date", *DATE_TAGS):
        for source in (dataset.metadata, {k.upper(): v for k, v in dataset.metadata.items()}):
            if key in source:
                parsed = parse_acquisition_date(source[key])
                if parsed is not None:
                    return parsed
    return None


def describe_raster(path: str, image_id: str | None = None) -> ImageMetadata:
    """Read ``path`` and describe it as :class:`ImageMetadata`.

    Raises :class:`app.tools.raster.model.RasterError` when the file cannot be
    opened, so an unreadable upload fails at ingestion rather than deep inside
    a tool.
    """
    dataset = open_raster(path)
    return describe_dataset(dataset)


def describe_dataset(dataset: RasterDataset) -> ImageMetadata:
    """Describe an already-opened dataset as :class:`ImageMetadata`."""
    sensor = dataset.metadata.get("sensor")
    return ImageMetadata(
        acquisition_date=find_acquisition_date(dataset),
        modality=infer_modality(dataset),
        sensor=sensor if isinstance(sensor, str) else None,
        crs=dataset.georeference.crs,
        width=dataset.width,
        height=dataset.height,
        bands=logical_band_names(dataset),
    )
