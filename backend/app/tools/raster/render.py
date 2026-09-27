"""Rendering a raster into a picture: for a vision model, and for the map.

Satellite rasters are 16-bit reflectance or backscatter in decibels; screens
and vision-language models read 8-bit pictures. How a scene is rendered
changes what is seen, so the choice is recorded and handed on with the image:

* optical with red, green and blue: **true colour**, as the eye would see it;
* optical without blue: **false colour** (NIR, red, green), where vegetation
  is red -- a model is told so, or it would call a forest a fire;
* SAR: **backscatter greyscale** in dB, where calm water is black and
  buildings are white -- stated, because it is not a photograph;
* an 8-bit three-band image with no band names: shown as the RGB it already is.

Each channel is stretched between its 2nd and 98th percentiles, the usual
display stretch, so a few very bright pixels cannot flatten the rest. A pair of
scenes can share one stretch (:func:`render_pair`): comparing two dates only
means something if a brighter pixel is brighter on the ground, not merely
stretched differently. Pictures are decimated to at most ``max_side`` pixels
and PNG-encoded with the standard library alone.
"""

from __future__ import annotations

import math
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

from app.tools.base import Artifact, ToolExecutionError, ToolRequest
from app.tools.raster.backends import has_numpy
from app.tools.raster.bands import normalise, resolve_band
from app.tools.raster.model import BandArray, RasterDataset, RasterError, is_projected_crs
from app.tools.sar.backscatter import POLARISATION_PREFERENCE, detect_units

#: What a vision model is shown.
DEFAULT_MAX_SIDE = 768
#: The underlay of the map overlay; matches the frontend's decode budget so the
#: picture and the result raster line up pixel for pixel.
OVERLAY_MAX_SIDE = 1024
STRETCH_PERCENTILES = (2.0, 98.0)
#: Sentinel-2 SCL classes whose brightness says nothing about the ground:
#: saturated, cloud shadow, medium and high cloud, cirrus, snow. They are still
#: drawn -- a cloud renders white, as it looks -- but they do not set the
#: stretch; otherwise a partly cloudy scene stretches to the cloud tops and the
#: ground comes out nearly black, for the reader and the vision model alike.
STRETCH_EXCLUDED_SCL = frozenset({1, 3, 8, 9, 10, 11})


@dataclass
class Preview:
    """A rendered PNG and an honest description of how it was made."""

    png: bytes
    width: int
    height: int
    kind: str
    description: str
    #: How many source pixels one preview pixel spans, along each axis.
    decimation: float
    #: The (low, high) stretch applied to each channel.
    limits: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class _Sampled:
    kind: str
    description: str
    width: int
    height: int
    decimation: float
    samples: list[list[float]]
    #: Per preview pixel, whether it may set the stretch; ``None`` means all may.
    clear: list[bool] | None = None

    def stretch_values(self, channel: int) -> list[float]:
        values = self.samples[channel]
        if self.clear is None:
            return values
        return [value for value, ok in zip(values, self.clear) if ok]


def render_preview(
    dataset: RasterDataset,
    max_side: int = DEFAULT_MAX_SIDE,
    limits: list[tuple[float, float]] | None = None,
) -> Preview:
    """Render ``dataset`` as an RGB PNG no larger than ``max_side``."""
    sampled = _sample_dataset(dataset, max_side)
    return _encode(sampled, limits or _default_limits(sampled))


def render_pair(
    first: RasterDataset, second: RasterDataset, max_side: int = DEFAULT_MAX_SIDE
) -> tuple[Preview, Preview]:
    """Render two scenes, sharing one stretch when they are rendered alike."""
    a, b = _sample_dataset(first, max_side), _sample_dataset(second, max_side)
    if a.kind == b.kind and a.kind != "rgb8" and len(a.samples) == len(b.samples):
        shared = [
            _limits(a.stretch_values(channel) + b.stretch_values(channel))
            for channel in range(len(a.samples))
        ]
        return _encode(a, shared), _encode(b, shared)
    return _encode(a, _default_limits(a)), _encode(b, _default_limits(b))


def write_preview(
    request: ToolRequest,
    dataset: RasterDataset,
    source_path: str,
    artifact_id: str = "scene_preview",
    max_side: int = OVERLAY_MAX_SIDE,
    preview: Preview | None = None,
) -> Artifact:
    """Write a preview PNG next to a task's outputs and describe it."""
    preview = preview or render_preview(dataset, max_side)
    stem = os.path.splitext(os.path.basename(source_path))[0]
    path = os.path.join(request.resolved_output_directory(), f"{stem}_{artifact_id}.png")
    with open(path, "wb") as handle:
        handle.write(preview.png)
    return Artifact(
        artifact_id=artifact_id,
        kind="image",
        path=path,
        format="PNG",
        description=(
            f"{preview.width}x{preview.height} picture of the analysed area: "
            f"{preview.description}."
        ),
    )


# ============================================================
# CHOOSING WHAT TO SHOW
# ============================================================
def _choose_bands(
    dataset: RasterDataset, sensor: str | None
) -> tuple[str, list[BandArray], str]:
    names = {normalise(band.name): band for band in dataset.bands}
    for polarisation in POLARISATION_PREFERENCE:
        if polarisation in names:
            band = names[polarisation]
            return (
                "sar_greyscale",
                [band],
                f"radar backscatter ({band.name} polarisation) shown in greyscale: "
                "dark areas are smooth surfaces such as calm water, bright areas "
                "are rough surfaces, buildings or steep slopes. It is not a photograph",
            )

    def find(role: str) -> BandArray | None:
        try:
            return resolve_band(dataset, role, sensor)
        except RasterError:
            return None

    red, green, blue, nir = find("red"), find("green"), find("blue"), find("nir")
    if red and green and blue:
        return (
            "true_colour",
            [red, green, blue],
            f"true colour (red={red.name}, green={green.name}, blue={blue.name}), "
            "as the eye would see it",
        )
    if nir and red and green:
        return (
            "false_colour",
            [nir, red, green],
            f"false colour infrared (red={nir.name} near-infrared, green={red.name} "
            f"red, blue={green.name} green): healthy vegetation appears bright red "
            "and water appears dark",
        )
    if dataset.band_count in (3, 4) and dataset.dtype == "uint8":
        # An ordinary 8-bit picture (a benchmark tile, an exported quicklook):
        # its bands are already red, green and blue.
        return "rgb8", dataset.bands[:3], "an 8-bit RGB picture of the scene"
    if not dataset.bands:
        raise ToolExecutionError("The raster has no bands to render.")
    band = dataset.bands[0]
    return "greyscale", [band], f"a single band ({band.name}) shown in greyscale"


# ============================================================
# SAMPLING AND STRETCHING
# ============================================================
def _sample_dataset(dataset: RasterDataset, max_side: int) -> _Sampled:
    kind, bands, description = _choose_bands(dataset, dataset.metadata.get("sensor"))
    decimation = max(1.0, max(dataset.width, dataset.height) / max_side)
    out_width = max(1, round(dataset.width / decimation))
    out_height = max(1, round(dataset.height / decimation))
    samples = [
        _sample(band, dataset.width, dataset.height, out_width, out_height, kind)
        for band in bands
    ]
    clear = _clear_of_cloud(dataset, out_width, out_height)
    return _Sampled(kind, description, out_width, out_height, decimation, samples, clear)


def _clear_of_cloud(dataset: RasterDataset, out_width: int, out_height: int) -> list[bool] | None:
    """Which preview pixels the scene's own SCL band calls clear, if it has one."""
    scl = next((band for band in dataset.bands if normalise(band.name) == "scl"), None)
    if scl is None:
        return None
    codes = _sample(scl, dataset.width, dataset.height, out_width, out_height, "mask")
    clear = [math.isfinite(code) and int(code) not in STRETCH_EXCLUDED_SCL for code in codes]
    # A scene that is all cloud still needs a stretch; use every pixel then.
    return clear if any(clear) else None


def _default_limits(sampled: _Sampled) -> list[tuple[float, float]]:
    if sampled.kind == "rgb8":
        return [(0.0, 255.0)] * len(sampled.samples)
    return [_limits(sampled.stretch_values(channel)) for channel in range(len(sampled.samples))]


def _encode(sampled: _Sampled, limits: list[tuple[float, float]]) -> Preview:
    channels = [
        _to_bytes(values, low, high) for values, (low, high) in zip(sampled.samples, limits)
    ]
    if len(channels) == 1:
        channels = channels * 3
    rows = _interleave(channels, sampled.width, sampled.height)
    return Preview(
        png=encode_png(sampled.width, sampled.height, rows),
        width=sampled.width,
        height=sampled.height,
        kind=sampled.kind,
        description=sampled.description,
        decimation=sampled.decimation,
        limits=list(limits),
    )


def _sample(band: BandArray, width: int, height: int, out_width: int, out_height: int, kind: str) -> list[float]:
    """Nearest-neighbour decimation to the preview grid, as floats with NaN nodata.

    SAR in linear power is converted to dB first, because a linear stretch of
    power renders almost every pixel black.
    """
    to_db = kind == "sar_greyscale" and _is_linear(band)
    rows = [min(height - 1, int((row + 0.5) * height / out_height)) for row in range(out_height)]
    cols = [min(width - 1, int((col + 0.5) * width / out_width)) for col in range(out_width)]
    nodata = band.nodata

    if has_numpy():
        import numpy

        grid = numpy.asarray(band.values, dtype=numpy.float64).reshape(height, width)
        picked = grid[numpy.ix_(rows, cols)].reshape(-1)
        if nodata is not None and not math.isnan(nodata):
            picked = numpy.where(picked == nodata, numpy.nan, picked)
        if to_db:
            with numpy.errstate(divide="ignore", invalid="ignore"):
                picked = numpy.where(picked > 0, 10.0 * numpy.log10(picked), numpy.nan)
        return picked.tolist()

    values: list[float] = []
    for row in rows:
        offset = row * width
        for col in cols:
            value = float(band.values[offset + col])
            if nodata is not None and not math.isnan(nodata) and value == nodata:
                value = float("nan")
            if to_db:
                value = 10.0 * math.log10(value) if value > 0 else float("nan")
            values.append(value)
    return values


def _is_linear(band: BandArray) -> bool:
    try:
        return detect_units(band) == "linear"
    except ToolExecutionError:
        # Uncalibrated digital numbers: stretch them as they are.
        return False


def _limits(values: list[float]) -> tuple[float, float]:
    """The stretch percentiles of the finite ``values``."""
    if has_numpy():
        import numpy

        array = numpy.asarray(values, dtype=numpy.float64)
        array = array[numpy.isfinite(array)]
        if array.size == 0:
            return 0.0, 1.0
        low, high = numpy.percentile(array, STRETCH_PERCENTILES, method="lower")
        return float(low), float(high)

    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return 0.0, 1.0
    last = len(finite) - 1
    return (
        finite[int(STRETCH_PERCENTILES[0] / 100 * last)],
        finite[int(STRETCH_PERCENTILES[1] / 100 * last)],
    )


def _to_bytes(values: list[float], low: float, high: float) -> list[int]:
    """Map values to 0..255 between ``low`` and ``high``; nodata is 0."""
    span = (high - low) or 1.0
    if has_numpy():
        import numpy

        array = numpy.asarray(values, dtype=numpy.float64)
        finite = numpy.isfinite(array)
        scaled = numpy.clip((numpy.where(finite, array, low) - low) / span * 255.0 + 0.5, 0, 255)
        return numpy.where(finite, scaled, 0).astype(numpy.uint8).tolist()
    return [
        int(max(0.0, min(255.0, (value - low) / span * 255.0 + 0.5)))
        if math.isfinite(value)
        else 0
        for value in values
    ]


def _interleave(channels: list[list[int]], width: int, height: int) -> list[bytes]:
    red, green, blue = channels
    rows = []
    for row in range(height):
        start = row * width
        line = bytearray(width * 3)
        line[0::3] = bytes(red[start:start + width])
        line[1::3] = bytes(green[start:start + width])
        line[2::3] = bytes(blue[start:start + width])
        rows.append(bytes(line))
    return rows


def encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    """Encode 8-bit RGB rows as a PNG, using only :mod:`zlib` and :mod:`struct`."""
    if len(rows) != height or any(len(row) != width * 3 for row in rows):
        raise ValueError("PNG rows do not match the declared size.")

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Filter type 0 ("None") on every scanline.
    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def describe_footprint(dataset: RasterDataset, preview: Preview) -> dict[str, Any]:
    """Ground size of the scene and of one preview pixel, when it is knowable."""
    georeference = dataset.georeference
    size = georeference.pixel_size
    if not georeference.is_georeferenced or size is None or not is_projected_crs(georeference.crs):
        return {}
    return {
        "source_pixel_metres": [size[0], size[1]],
        "preview_pixel_metres": [size[0] * preview.decimation, size[1] * preview.decimation],
        "footprint_km": [dataset.width * size[0] / 1000.0, dataset.height * size[1] / 1000.0],
    }


__all__ = [
    "DEFAULT_MAX_SIDE",
    "OVERLAY_MAX_SIDE",
    "Preview",
    "describe_footprint",
    "encode_png",
    "render_pair",
    "render_preview",
    "write_preview",
]
