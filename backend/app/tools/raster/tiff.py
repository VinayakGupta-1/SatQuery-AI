"""A dependency-free baseline TIFF/GeoTIFF reader and writer.

This exists so SatQuery can read and write *real* GeoTIFF files without
requiring GDAL to be installed. It implements the subset of the TIFF 6.0
specification that satellite products actually use for uncompressed data:

* little- and big-endian byte order
* strip-based and tile-based layouts
* chunky (interleaved) and planar sample configurations
* 8/16/32-bit integer and 32/64-bit float samples
* the GeoTIFF tags carrying CRS and the affine transform

Compressed rasters (DEFLATE, LZW, JPEG) are *not* decoded here; those are
delegated to rasterio by :mod:`app.tools.raster.io`, which raises a clear
error asking for rasterio when it is unavailable. Nothing in this module
guesses or fabricates pixel values: if a file cannot be decoded exactly, it
raises rather than returning approximate data.
"""

from __future__ import annotations

import array
import struct
import sys
import xml.etree.ElementTree as ElementTree
from typing import Any, BinaryIO
from xml.sax.saxutils import escape

from app.tools.raster.model import (
    DTYPE_TO_ITEMSIZE,
    DTYPE_TO_TYPECODE,
    BandArray,
    GeoReference,
    RasterDataset,
    RasterError,
    UnsupportedRasterError,
    new_sample_buffer,
)

# ============================================================
# TIFF CONSTANTS
# ============================================================
TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_STRIP_OFFSETS = 273
TAG_SAMPLES_PER_PIXEL = 277
TAG_ROWS_PER_STRIP = 278
TAG_STRIP_BYTE_COUNTS = 279
TAG_PLANAR_CONFIG = 284
TAG_TILE_WIDTH = 322
TAG_TILE_LENGTH = 323
TAG_TILE_OFFSETS = 324
TAG_TILE_BYTE_COUNTS = 325
TAG_SAMPLE_FORMAT = 339
TAG_MODEL_PIXEL_SCALE = 33550
TAG_MODEL_TIEPOINT = 33922
TAG_MODEL_TRANSFORMATION = 34264
TAG_GEO_KEY_DIRECTORY = 34735
TAG_GEO_DOUBLE_PARAMS = 34736
TAG_GEO_ASCII_PARAMS = 34737
TAG_GDAL_METADATA = 42112
TAG_GDAL_NODATA = 42113

COMPRESSION_NONE = 1

# GeoTIFF key identifiers.
KEY_GT_MODEL_TYPE = 1024
KEY_GT_RASTER_TYPE = 1025
KEY_GEOGRAPHIC_TYPE = 2048
KEY_PROJECTED_CS_TYPE = 3072

# TIFF field type -> (struct code, byte size)
FIELD_TYPES: dict[int, tuple[str, int]] = {
    1: ("B", 1),   # BYTE
    2: ("c", 1),   # ASCII
    3: ("H", 2),   # SHORT
    4: ("I", 4),   # LONG
    5: ("II", 8),  # RATIONAL
    6: ("b", 1),   # SBYTE
    7: ("B", 1),   # UNDEFINED
    8: ("h", 2),   # SSHORT
    9: ("i", 4),   # SLONG
    10: ("ii", 8),  # SRATIONAL
    11: ("f", 4),  # FLOAT
    12: ("d", 8),  # DOUBLE
}

# (sample_format, bits_per_sample) -> dtype name
SAMPLE_FORMAT_UINT = 1
SAMPLE_FORMAT_INT = 2
SAMPLE_FORMAT_FLOAT = 3

SAMPLE_TO_DTYPE: dict[tuple[int, int], str] = {
    (SAMPLE_FORMAT_UINT, 8): "uint8",
    (SAMPLE_FORMAT_UINT, 16): "uint16",
    (SAMPLE_FORMAT_UINT, 32): "uint32",
    (SAMPLE_FORMAT_INT, 8): "int8",
    (SAMPLE_FORMAT_INT, 16): "int16",
    (SAMPLE_FORMAT_INT, 32): "int32",
    (SAMPLE_FORMAT_FLOAT, 32): "float32",
    (SAMPLE_FORMAT_FLOAT, 64): "float64",
}

DTYPE_TO_SAMPLE: dict[str, tuple[int, int]] = {
    dtype: sample for sample, dtype in SAMPLE_TO_DTYPE.items()
}


# ============================================================
# GDAL METADATA (tag 42112)
# ============================================================
# GDAL stores band descriptions and dataset tags in a small XML document under
# tag 42112. Reading and writing it is what lets band identity -- "this plane
# is B8" -- survive inside the file itself rather than in a sidecar. Without
# it, a raster that changes hands loses the very names the tools resolve.
def encode_gdal_metadata(
    band_names: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bytes | None:
    """Build a GDALMetadata document, or ``None`` when there is nothing to say."""
    items: list[str] = []

    for index, name in enumerate(band_names or []):
        if not name:
            continue
        items.append(
            f'<Item name="DESCRIPTION" sample="{index}" role="description">'
            f"{escape(str(name))}</Item>"
        )

    for key, value in (metadata or {}).items():
        if value is None or key == "band_names":
            continue
        items.append(f'<Item name="{escape(str(key))}">{escape(str(value))}</Item>')

    if not items:
        return None
    return ("<GDALMetadata>" + "".join(items) + "</GDALMetadata>\x00").encode("utf-8")


def decode_gdal_metadata(text: str | None) -> tuple[dict[int, str], dict[str, str]]:
    """Parse a GDALMetadata document into band descriptions and dataset tags."""
    if not text or not text.strip():
        return {}, {}
    try:
        root = ElementTree.fromstring(text.strip().rstrip("\x00"))
    except ElementTree.ParseError:
        return {}, {}

    descriptions: dict[int, str] = {}
    tags: dict[str, str] = {}
    for item in root.findall("Item"):
        value = (item.text or "").strip()
        if not value:
            continue
        name = item.get("name", "")
        if name == "DESCRIPTION" and item.get("sample") is not None:
            try:
                descriptions[int(item.get("sample", ""))] = value
            except ValueError:
                continue
        elif name:
            tags[name] = value
    return descriptions, tags


def is_tiff(path: str) -> bool:
    """Return True when ``path`` starts with a TIFF magic header."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(4)
    except OSError:
        return False
    return header[:2] in (b"II", b"MM") and len(header) == 4


# ============================================================
# READING
# ============================================================
class _TiffReader:
    """Parses one baseline TIFF file into a :class:`RasterDataset`."""

    def __init__(self, handle: BinaryIO, path: str) -> None:
        self.handle = handle
        self.path = path
        self.endian = "<"
        self.tags: dict[int, list[Any]] = {}

    # -- primitives ------------------------------------------------
    def _unpack(self, code: str, data: bytes) -> tuple[Any, ...]:
        return struct.unpack(self.endian + code, data)

    def _read_at(self, offset: int, size: int) -> bytes:
        self.handle.seek(offset)
        data = self.handle.read(size)
        if len(data) != size:
            raise RasterError(
                f"{self.path} is truncated: expected {size} bytes at offset "
                f"{offset} but read {len(data)}."
            )
        return data

    # -- header and directory --------------------------------------
    def read_header(self) -> int:
        header = self._read_at(0, 8)
        if header[:2] == b"II":
            self.endian = "<"
        elif header[:2] == b"MM":
            self.endian = ">"
        else:
            raise UnsupportedRasterError(f"{self.path} is not a TIFF file.")

        magic, ifd_offset = self._unpack("HI", header[2:8])
        if magic == 43:
            raise UnsupportedRasterError(
                f"{self.path} is a BigTIFF. Install rasterio to read BigTIFF files."
            )
        if magic != 42:
            raise UnsupportedRasterError(
                f"{self.path} has an unrecognised TIFF version marker ({magic})."
            )
        return ifd_offset

    def read_ifd(self, offset: int) -> None:
        (entry_count,) = self._unpack("H", self._read_at(offset, 2))
        entries = self._read_at(offset + 2, entry_count * 12)
        for index in range(entry_count):
            self._read_entry(entries[index * 12 : (index + 1) * 12])

    def _read_entry(self, entry: bytes) -> None:
        tag, field_type, count = self._unpack("HHI", entry[:8])
        payload = entry[8:12]
        if field_type not in FIELD_TYPES:
            # Unknown field types are skipped rather than failing the read;
            # baseline decoding never depends on them.
            return

        code, item_size = FIELD_TYPES[field_type]
        total = item_size * count
        if total > 4:
            (value_offset,) = self._unpack("I", payload)
            payload = self._read_at(value_offset, total)

        if field_type == 2:  # ASCII
            text = payload[:count].split(b"\x00")[0].decode("utf-8", "replace")
            self.tags[tag] = [text]
            return

        if field_type in (5, 10):  # RATIONAL / SRATIONAL
            parts = self._unpack(code * count, payload[:total])
            self.tags[tag] = [
                (parts[i * 2] / parts[i * 2 + 1]) if parts[i * 2 + 1] else 0.0
                for i in range(count)
            ]
            return

        self.tags[tag] = list(self._unpack(code * count, payload[:total]))

    # -- tag helpers ------------------------------------------------
    def get(self, tag: int, default: Any = None) -> Any:
        values = self.tags.get(tag)
        if not values:
            return default
        return values[0]

    def get_all(self, tag: int, default: list[Any] | None = None) -> list[Any]:
        return self.tags.get(tag, default if default is not None else [])

    # -- pixel decoding ---------------------------------------------
    def _decode_dtype(self, samples_per_pixel: int) -> str:
        bits = self.get_all(TAG_BITS_PER_SAMPLE, [1])
        if len(set(bits)) > 1:
            raise UnsupportedRasterError(
                f"{self.path} mixes sample depths {sorted(set(bits))}; "
                "SatQuery requires a uniform depth across bands."
            )
        formats = self.get_all(TAG_SAMPLE_FORMAT, [SAMPLE_FORMAT_UINT])
        if len(set(formats)) > 1:
            raise UnsupportedRasterError(
                f"{self.path} mixes sample formats; SatQuery requires a uniform format."
            )

        key = (int(formats[0]), int(bits[0]))
        dtype = SAMPLE_TO_DTYPE.get(key)
        if dtype is None:
            raise UnsupportedRasterError(
                f"{self.path} uses sample format {key[0]} at {key[1]} bits, "
                "which SatQuery cannot decode without rasterio."
            )
        return dtype

    def _to_samples(self, raw: bytes, dtype: str) -> array.array:
        typecode = DTYPE_TO_TYPECODE[dtype]
        values = array.array(typecode)
        if values.itemsize != DTYPE_TO_ITEMSIZE[dtype]:
            raise UnsupportedRasterError(
                f"This platform stores '{typecode}' in {values.itemsize} bytes; "
                f"{dtype} decoding requires {DTYPE_TO_ITEMSIZE[dtype]}."
            )
        usable = len(raw) - (len(raw) % values.itemsize)
        values.frombytes(raw[:usable])
        file_endian = "little" if self.endian == "<" else "big"
        if file_endian != sys.byteorder and values.itemsize > 1:
            values.byteswap()
        return values

    def read_pixels(self) -> tuple[list[array.array], int, int, str]:
        width = int(self.get(TAG_IMAGE_WIDTH, 0))
        height = int(self.get(TAG_IMAGE_LENGTH, 0))
        if width <= 0 or height <= 0:
            raise RasterError(f"{self.path} declares an empty {width}x{height} grid.")

        compression = int(self.get(TAG_COMPRESSION, COMPRESSION_NONE))
        if compression != COMPRESSION_NONE:
            raise UnsupportedRasterError(
                f"{self.path} uses TIFF compression {compression}. Install rasterio "
                "(pip install rasterio) to read compressed GeoTIFF files."
            )

        samples = int(self.get(TAG_SAMPLES_PER_PIXEL, 1))
        planar = int(self.get(TAG_PLANAR_CONFIG, 1))
        dtype = self._decode_dtype(samples)

        bands = [new_sample_buffer(dtype, width * height) for _ in range(samples)]

        if TAG_TILE_OFFSETS in self.tags:
            self._read_tiled(bands, width, height, samples, planar, dtype)
        else:
            self._read_stripped(bands, width, height, samples, planar, dtype)

        return bands, width, height, dtype

    def _read_stripped(
        self,
        bands: list[array.array],
        width: int,
        height: int,
        samples: int,
        planar: int,
        dtype: str,
    ) -> None:
        offsets = [int(value) for value in self.get_all(TAG_STRIP_OFFSETS)]
        counts = [int(value) for value in self.get_all(TAG_STRIP_BYTE_COUNTS)]
        rows_per_strip = int(self.get(TAG_ROWS_PER_STRIP, height) or height)
        rows_per_strip = min(rows_per_strip, height)
        if not offsets:
            raise RasterError(f"{self.path} has no strip offsets.")
        if len(counts) != len(offsets):
            raise RasterError(f"{self.path} has mismatched strip offsets and lengths.")

        strips_per_plane = (height + rows_per_strip - 1) // rows_per_strip

        for strip_index, (offset, count) in enumerate(zip(offsets, counts)):
            values = self._to_samples(self._read_at(offset, count), dtype)
            if planar == 2:
                plane = strip_index // strips_per_plane
                row_start = (strip_index % strips_per_plane) * rows_per_strip
                self._scatter_plane(bands[plane], values, width, height, row_start)
            else:
                row_start = strip_index * rows_per_strip
                self._scatter_chunky(bands, values, width, height, samples, row_start)

    def _scatter_plane(
        self,
        band: array.array,
        values: array.array,
        width: int,
        height: int,
        row_start: int,
    ) -> None:
        rows = min(len(values) // width, height - row_start)
        if rows <= 0:
            return
        start = row_start * width
        band[start : start + rows * width] = values[: rows * width]

    def _scatter_chunky(
        self,
        bands: list[array.array],
        values: array.array,
        width: int,
        height: int,
        samples: int,
        row_start: int,
    ) -> None:
        rows = min(len(values) // (width * samples), height - row_start)
        if rows <= 0:
            return
        span = rows * width
        start = row_start * width
        if samples == 1:
            bands[0][start : start + span] = values[:span]
            return
        for sample_index, band in enumerate(bands):
            band[start : start + span] = values[sample_index : span * samples : samples]

    def _read_tiled(
        self,
        bands: list[array.array],
        width: int,
        height: int,
        samples: int,
        planar: int,
        dtype: str,
    ) -> None:
        tile_width = int(self.get(TAG_TILE_WIDTH, 0))
        tile_height = int(self.get(TAG_TILE_LENGTH, 0))
        if tile_width <= 0 or tile_height <= 0:
            raise RasterError(f"{self.path} declares invalid tile dimensions.")

        offsets = [int(value) for value in self.get_all(TAG_TILE_OFFSETS)]
        counts = [int(value) for value in self.get_all(TAG_TILE_BYTE_COUNTS)]
        if len(counts) != len(offsets):
            raise RasterError(f"{self.path} has mismatched tile offsets and lengths.")

        across = (width + tile_width - 1) // tile_width
        down = (height + tile_height - 1) // tile_height
        tiles_per_plane = across * down

        for tile_index, (offset, count) in enumerate(zip(offsets, counts)):
            values = self._to_samples(self._read_at(offset, count), dtype)
            if planar == 2:
                plane = tile_index // tiles_per_plane
                local = tile_index % tiles_per_plane
                targets = [bands[plane]]
                stride = 1
            else:
                local = tile_index
                targets = bands
                stride = samples

            origin_row = (local // across) * tile_height
            origin_column = (local % across) * tile_width

            for tile_row in range(tile_height):
                row = origin_row + tile_row
                if row >= height:
                    break
                columns = min(tile_width, width - origin_column)
                if columns <= 0:
                    break
                source = tile_row * tile_width * stride
                target = row * width + origin_column
                for sample_index, band in enumerate(targets):
                    band[target : target + columns] = values[
                        source + sample_index : source + columns * stride : stride
                    ]

    # -- georeferencing ---------------------------------------------
    def read_georeference(self) -> GeoReference:
        transform: tuple[float, ...] | None = None

        matrix = self.get_all(TAG_MODEL_TRANSFORMATION)
        if len(matrix) >= 16:
            transform = (
                float(matrix[3]),
                float(matrix[0]),
                float(matrix[1]),
                float(matrix[7]),
                float(matrix[4]),
                float(matrix[5]),
            )
        else:
            scale = self.get_all(TAG_MODEL_PIXEL_SCALE)
            tiepoint = self.get_all(TAG_MODEL_TIEPOINT)
            if len(scale) >= 2 and len(tiepoint) >= 6:
                # Tiepoint maps raster (i, j, k) to model (x, y, z).
                origin_x = float(tiepoint[3]) - float(tiepoint[0]) * float(scale[0])
                origin_y = float(tiepoint[4]) + float(tiepoint[1]) * float(scale[1])
                transform = (
                    origin_x,
                    float(scale[0]),
                    0.0,
                    origin_y,
                    0.0,
                    -float(scale[1]),
                )

        return GeoReference(crs=self._read_crs(), transform=transform)  # type: ignore[arg-type]

    def _read_crs(self) -> str | None:
        directory = self.get_all(TAG_GEO_KEY_DIRECTORY)
        if len(directory) < 4:
            return None
        key_count = int(directory[3])
        for index in range(key_count):
            base = 4 + index * 4
            if base + 3 >= len(directory):
                break
            key_id, location, _count, value = (int(v) for v in directory[base : base + 4])
            if location != 0:
                continue  # value lives in another tag; only EPSG codes are inline
            if key_id in (KEY_PROJECTED_CS_TYPE, KEY_GEOGRAPHIC_TYPE):
                if 0 < value < 32767:
                    return f"EPSG:{value}"
        return None

    def read_nodata(self) -> float | None:
        raw = self.get(TAG_GDAL_NODATA)
        if raw is None:
            return None
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            return None


def read_tiff(path: str, band_names: list[str] | None = None) -> RasterDataset:
    """Read a baseline (uncompressed) TIFF/GeoTIFF into a dataset."""
    with open(path, "rb") as handle:
        reader = _TiffReader(handle, path)
        reader.read_ifd(reader.read_header())
        planes, width, height, dtype = reader.read_pixels()
        georeference = reader.read_georeference()
        nodata = reader.read_nodata()
        descriptions, tags = decode_gdal_metadata(reader.get(TAG_GDAL_METADATA))

    # Names supplied by the caller win; then names stored in the file itself;
    # then a positional fallback that claims no meaning beyond band order.
    names = band_names or [
        descriptions.get(index) or f"B{index + 1}" for index in range(len(planes))
    ]
    if len(names) != len(planes):
        raise RasterError(
            f"{path} contains {len(planes)} band(s) but {len(names)} name(s) were supplied."
        )

    bands = [
        BandArray(
            name=name,
            width=width,
            height=height,
            values=values,
            dtype=dtype,
            nodata=nodata,
        )
        for name, values in zip(names, planes)
    ]
    return RasterDataset(
        width=width,
        height=height,
        bands=bands,
        georeference=georeference,
        dtype=dtype,
        nodata=nodata,
        path=path,
        metadata=dict(tags),
    )


# ============================================================
# WRITING
# ============================================================
def _geo_key_directory(crs: str | None) -> list[int] | None:
    """Build a minimal GeoKeyDirectory for an ``EPSG:<code>`` CRS."""
    if not crs or not crs.upper().startswith("EPSG:"):
        return None
    try:
        code = int(crs.split(":", 1)[1])
    except ValueError:
        return None

    geographic = 4000 <= code <= 4999
    keys = [
        (KEY_GT_MODEL_TYPE, 0, 1, 2 if geographic else 1),
        (KEY_GT_RASTER_TYPE, 0, 1, 1),  # PixelIsArea
        (KEY_GEOGRAPHIC_TYPE if geographic else KEY_PROJECTED_CS_TYPE, 0, 1, code),
    ]
    directory = [1, 1, 0, len(keys)]
    for key in keys:
        directory.extend(key)
    return directory


def write_tiff(
    path: str,
    bands: list[BandArray],
    georeference: GeoReference | None = None,
    dtype: str | None = None,
    nodata: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Write bands to an uncompressed, strip-based little-endian GeoTIFF.

    Band names and ``metadata`` are stored in the file's GDALMetadata tag, so
    a raster written here stays self-describing when it is copied elsewhere.
    """
    if not bands:
        raise RasterError("At least one band is required to write a GeoTIFF.")

    width, height = bands[0].width, bands[0].height
    for band in bands:
        if (band.width, band.height) != (width, height):
            raise RasterError("All bands written to one GeoTIFF must share a grid.")

    dtype = dtype or bands[0].dtype
    if dtype not in DTYPE_TO_SAMPLE:
        raise UnsupportedRasterError(f"Cannot write GeoTIFF samples of dtype {dtype}.")
    sample_format, bits = DTYPE_TO_SAMPLE[dtype]
    typecode = DTYPE_TO_TYPECODE[dtype]
    samples = len(bands)

    # Interleave the bands into a single chunky strip.
    if samples == 1:
        pixels = array.array(typecode, bands[0].values)
    else:
        pixels = new_sample_buffer(dtype, width * height * samples)
        for index, band in enumerate(bands):
            pixels[index::samples] = array.array(typecode, band.values)
    if sys.byteorder != "little" and pixels.itemsize > 1:
        pixels.byteswap()
    body = pixels.tobytes()

    entries: list[tuple[int, int, int, Any]] = [
        (TAG_IMAGE_WIDTH, 4, 1, [width]),
        (TAG_IMAGE_LENGTH, 4, 1, [height]),
        (TAG_BITS_PER_SAMPLE, 3, samples, [bits] * samples),
        (TAG_COMPRESSION, 3, 1, [COMPRESSION_NONE]),
        (TAG_PHOTOMETRIC, 3, 1, [1]),  # BlackIsZero
        (TAG_STRIP_OFFSETS, 4, 1, [8]),
        (TAG_SAMPLES_PER_PIXEL, 3, 1, [samples]),
        (TAG_ROWS_PER_STRIP, 4, 1, [height]),
        (TAG_STRIP_BYTE_COUNTS, 4, 1, [len(body)]),
        (TAG_PLANAR_CONFIG, 3, 1, [1]),
        (TAG_SAMPLE_FORMAT, 3, samples, [sample_format] * samples),
    ]

    if georeference and georeference.transform:
        origin_x, pixel_width, _, origin_y, _, pixel_height = georeference.transform
        entries.append(
            (TAG_MODEL_PIXEL_SCALE, 12, 3, [pixel_width, abs(pixel_height), 0.0])
        )
        entries.append(
            (TAG_MODEL_TIEPOINT, 12, 6, [0.0, 0.0, 0.0, origin_x, origin_y, 0.0])
        )
    if georeference:
        directory = _geo_key_directory(georeference.crs)
        if directory:
            entries.append((TAG_GEO_KEY_DIRECTORY, 3, len(directory), directory))

    if nodata is not None:
        text = f"{nodata}".encode("ascii") + b"\x00"
        entries.append((TAG_GDAL_NODATA, 2, len(text), text))

    document = encode_gdal_metadata([band.name for band in bands], metadata)
    if document:
        entries.append((TAG_GDAL_METADATA, 2, len(document), document))

    entries.sort(key=lambda entry: entry[0])

    ifd_offset = 8 + len(body)
    external_offset = ifd_offset + 2 + 12 * len(entries) + 4

    directory_bytes = bytearray(struct.pack("<H", len(entries)))
    external_bytes = bytearray()

    for tag, field_type, count, values in entries:
        code, item_size = FIELD_TYPES[field_type]
        if field_type == 2:
            payload = bytes(values)
        else:
            payload = struct.pack("<" + code * count, *values)

        directory_bytes += struct.pack("<HHI", tag, field_type, count)
        if len(payload) <= 4:
            directory_bytes += payload.ljust(4, b"\x00")
        else:
            directory_bytes += struct.pack("<I", external_offset + len(external_bytes))
            external_bytes += payload
            if len(external_bytes) % 2:  # keep values word-aligned
                external_bytes += b"\x00"

    directory_bytes += struct.pack("<I", 0)  # no further IFDs

    with open(path, "wb") as handle:
        handle.write(struct.pack("<2sHI", b"II", 42, ifd_offset))
        handle.write(body)
        handle.write(directory_bytes)
        handle.write(external_bytes)

    return path
