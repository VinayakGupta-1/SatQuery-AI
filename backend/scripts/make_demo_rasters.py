"""Write a pair of synthetic Sentinel-2-style scenes for trying the system out.

This exists so the frontend can be exercised end to end without hunting for a
real product first. The rasters are synthetic, but they are *real GeoTIFFs*:
georeferenced, four-band, uint16, band-named and sensor-tagged, written through
the same :mod:`app.tools.raster.io` writer the tools use. Everything computed
from them -- NDVI, NDWI, NDBI, change detection -- is therefore a genuine
computation over genuine input, not a canned answer.

Usage::

    python scripts/make_demo_rasters.py [output_directory]

Two scenes are produced, ten months apart over the same footprint, so the pair
is co-registered and can be used for bi-temporal change detection. The later
scene has a cleared block in the forest and a small reservoir drawdown.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.raster.io import write_raster, write_sidecar  # noqa: E402
from app.tools.raster.model import BandArray, GeoReference  # noqa: E402

SIZE = 512
#: UTM zone 43N, 10 m pixels, somewhere over central India.
GEOREFERENCE = GeoReference(
    crs="EPSG:32643",
    transform=(707000.0, 10.0, 0.0, 2412000.0, 0.0, -10.0),
)


def _terrain(x: int, y: int) -> float:
    """A smooth, deterministic landscape field in 0..1."""
    u = x / SIZE
    v = y / SIZE
    return (
        0.5
        + 0.28 * math.sin(u * 6.1 + 0.7) * math.cos(v * 4.3 - 0.4)
        + 0.16 * math.sin(u * 15.7 - 1.2) * math.sin(v * 13.1 + 0.9)
        + 0.06 * math.sin(u * 41.0) * math.cos(v * 37.0)
    )


def _is_river(x: int, y: int) -> bool:
    """A meandering channel across the scene."""
    centre = SIZE * 0.55 + math.sin(x / 62.0) * 46 + math.sin(x / 21.0) * 11
    return abs(y - centre) < 7


def _is_reservoir(x: int, y: int, radius: float) -> bool:
    return (x - SIZE * 0.78) ** 2 + (y - SIZE * 0.24) ** 2 < radius**2


def _is_town(x: int, y: int) -> bool:
    return SIZE * 0.12 < x < SIZE * 0.30 and SIZE * 0.68 < y < SIZE * 0.86


def _is_clearing(x: int, y: int) -> bool:
    """The block felled between the two dates."""
    return SIZE * 0.56 < x < SIZE * 0.74 and SIZE * 0.60 < y < SIZE * 0.79


def build_scene(cleared: bool, reservoir_radius: float) -> list[BandArray]:
    """Return B2, B3, B4, B8 for one date, as uint16 digital numbers."""
    blue: list[int] = []
    green: list[int] = []
    red: list[int] = []
    nir: list[int] = []

    for y in range(SIZE):
        for x in range(SIZE):
            vigour = max(0.0, min(1.0, _terrain(x, y)))

            if _is_river(x, y) or _is_reservoir(x, y, reservoir_radius):
                # Water: high green, near-total NIR absorption.
                b, g, r, n = 760, 980, 620, 190
            elif _is_town(x, y):
                # Built-up: flat, bright, moderate NIR.
                b, g, r, n = 1350, 1420, 1560, 1900
            elif cleared and _is_clearing(x, y):
                # Bare soil after felling.
                b, g, r, n = 1180, 1350, 1720, 2050
            else:
                # Vegetation, denser where the terrain field is higher.
                b = int(700 + 240 * (1 - vigour))
                g = int(980 + 320 * (1 - vigour))
                r = int(1500 - 900 * vigour)
                n = int(1600 + 3200 * vigour)

            blue.append(b)
            green.append(g)
            red.append(r)
            nir.append(n)

    return [
        BandArray("B2", SIZE, SIZE, blue, dtype="uint16"),
        BandArray("B3", SIZE, SIZE, green, dtype="uint16"),
        BandArray("B4", SIZE, SIZE, red, dtype="uint16"),
        BandArray("B8", SIZE, SIZE, nir, dtype="uint16"),
    ]


def write_scene(path: str, bands: list[BandArray], acquired: str) -> None:
    metadata = {
        "band_names": [band.name for band in bands],
        "sensor": "sentinel2",
        "acquisition_date": acquired,
    }
    write_raster(path, bands, GEOREFERENCE, dtype="uint16", metadata=metadata)
    write_sidecar(path, metadata)
    print(f"wrote {path}")


def main() -> None:
    directory = sys.argv[1] if len(sys.argv) > 1 else "demo_data"
    os.makedirs(directory, exist_ok=True)

    write_scene(
        os.path.join(directory, "scene_2023-11-04.tif"),
        build_scene(cleared=False, reservoir_radius=38),
        "2023-11-04",
    )
    write_scene(
        os.path.join(directory, "scene_2024-09-18.tif"),
        build_scene(cleared=True, reservoir_radius=24),
        "2024-09-18",
    )
    print(
        "\nTry: 'How healthy is the vegetation in this scene?' with one file,\n"
        "or  'Compare these two dates and show me what changed.' with both."
    )


if __name__ == "__main__":
    main()
