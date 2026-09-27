"""Write synthetic Sentinel-2 and Sentinel-1 style scenes for trying the system out.

This exists so the frontend can be exercised end to end without hunting for a
real product first. The rasters are synthetic, but they are *real GeoTIFFs*:
georeferenced, band-named and sensor-tagged, written through the same
:mod:`app.tools.raster.io` writer the tools use. Everything computed from them
-- indices, land cover, region detection, water mapping, change detection -- is
therefore a genuine computation over genuine input, not a canned answer.

Usage::

    python scripts/make_demo_rasters.py [output_directory]

Five scenes are produced over one footprint, so any pair is co-registered:

* two optical scenes (B2, B3, B4, B8, B11 as uint16 digital numbers), ten
  months apart. The later one has a cleared block in the forest and a
  reservoir drawdown.
* two SAR scenes (VV and VH as float32 sigma0 in dB, with speckle), before and
  during a monsoon flood that spreads across the river's floodplain.
* one optical scene on the flood date, partly under cloud, with a Sentinel-2
  SCL band: the pair it makes with the flooded SAR scene is what optical+SAR
  fusion is for.
"""

from __future__ import annotations

import math
import os
import random
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


def _river_distance(x: int, y: int) -> float:
    """Distance in pixels from the centreline of a meandering river."""
    centre = SIZE * 0.55 + math.sin(x / 62.0) * 46 + math.sin(x / 21.0) * 11
    return abs(y - centre)


def _is_river(x: int, y: int) -> bool:
    """A meandering channel across the scene."""
    return _river_distance(x, y) < 7


def _is_reservoir(x: int, y: int, radius: float) -> bool:
    return (x - SIZE * 0.78) ** 2 + (y - SIZE * 0.24) ** 2 < radius**2


def _is_town(x: int, y: int) -> bool:
    return SIZE * 0.12 < x < SIZE * 0.30 and SIZE * 0.68 < y < SIZE * 0.86


def _is_clearing(x: int, y: int) -> bool:
    """The block felled between the two dates."""
    return SIZE * 0.56 < x < SIZE * 0.74 and SIZE * 0.60 < y < SIZE * 0.79


def _is_flooded(x: int, y: int) -> bool:
    """The floodplain the river spreads across during the monsoon."""
    reach = 34 + 10 * math.sin(x / 37.0)
    return SIZE * 0.08 < x < SIZE * 0.92 and _river_distance(x, y) < reach


def build_scene(cleared: bool, reservoir_radius: float) -> list[BandArray]:
    """Return B2, B3, B4, B8, B11 for one date, as uint16 digital numbers."""
    blue: list[int] = []
    green: list[int] = []
    red: list[int] = []
    nir: list[int] = []
    swir: list[int] = []

    for y in range(SIZE):
        for x in range(SIZE):
            vigour = max(0.0, min(1.0, _terrain(x, y)))

            if _is_river(x, y) or _is_reservoir(x, y, reservoir_radius):
                # Water: high green, near-total NIR and SWIR absorption.
                b, g, r, n, s = 760, 980, 620, 190, 120
            elif _is_town(x, y):
                # Built-up: flat, bright, and brighter in SWIR than in NIR.
                b, g, r, n, s = 1350, 1420, 1560, 1900, 2400
            elif cleared and _is_clearing(x, y):
                # Freshly felled ground: bare, still moist, so SWIR stays
                # below NIR.
                b, g, r, n, s = 1180, 1350, 1720, 2050, 1950
            else:
                # Vegetation, denser where the terrain field is higher. Leaf
                # water absorbs SWIR, so SWIR falls as vigour rises.
                b = int(700 + 240 * (1 - vigour))
                g = int(980 + 320 * (1 - vigour))
                r = int(1500 - 900 * vigour)
                n = int(1600 + 3200 * vigour)
                s = int(1500 - 500 * vigour)

            blue.append(b)
            green.append(g)
            red.append(r)
            nir.append(n)
            swir.append(s)

    return [
        BandArray("B2", SIZE, SIZE, blue, dtype="uint16"),
        BandArray("B3", SIZE, SIZE, green, dtype="uint16"),
        BandArray("B4", SIZE, SIZE, red, dtype="uint16"),
        BandArray("B8", SIZE, SIZE, nir, dtype="uint16"),
        BandArray("B11", SIZE, SIZE, swir, dtype="uint16"),
    ]


#: Clouds over the flood-date optical scene: (centre x, centre y) as fractions
#: of the scene, and radius in pixels. Two sit over the flooded floodplain.
CLOUDS = ((0.30, 0.55, 64), (0.64, 0.58, 50), (0.86, 0.30, 38))


def _cloud(x: int, y: int) -> int:
    """0 clear, 1 thin cloud at an edge, 2 thick cloud."""
    for cx, cy, radius in CLOUDS:
        distance = math.hypot(x - cx * SIZE, y - cy * SIZE)
        if distance < radius * 0.8:
            return 2
        if distance < radius:
            return 1
    return 0


def build_flood_scene() -> list[BandArray]:
    """The optical scene on the flood date, partly under cloud, with its SCL band.

    Where the sky is clear the flooded floodplain is plainly water; where
    cloud sits over it the optical image sees only cloud. The Sentinel-2
    Scene Classification Layer marks which is which (4 vegetation, 5 not
    vegetated, 6 water, 8 and 9 cloud), as a real L2A product does.
    """
    columns: dict[str, list[int]] = {name: [] for name in ("B2", "B3", "B4", "B8", "B11", "SCL")}
    for y in range(SIZE):
        for x in range(SIZE):
            vigour = max(0.0, min(1.0, _terrain(x, y)))
            cloud = _cloud(x, y)
            if cloud == 2:
                values, scl = (7200, 7000, 6900, 7400, 5200), 9
            elif cloud == 1:
                values, scl = (5200, 5100, 5000, 5400, 4000), 8
            elif (
                _is_river(x, y)
                or _is_reservoir(x, y, 40)
                or (_is_flooded(x, y) and not _is_town(x, y))
            ):
                # Flood water carries sediment, so it is a little brighter in
                # the visible than the clear reservoir, still dark in NIR.
                values, scl = (860, 1080, 840, 260, 150), 6
            elif _is_town(x, y):
                values, scl = (1350, 1420, 1560, 1900, 2400), 5
            elif _is_clearing(x, y):
                values, scl = (1180, 1350, 1720, 2050, 1950), 5
            else:
                values = (
                    int(700 + 240 * (1 - vigour)),
                    int(980 + 320 * (1 - vigour)),
                    int(1500 - 900 * vigour),
                    int(1600 + 3200 * vigour),
                    int(1500 - 500 * vigour),
                )
                scl = 4
            for name, value in zip(("B2", "B3", "B4", "B8", "B11"), values):
                columns[name].append(value)
            columns["SCL"].append(scl)
    return [BandArray(name, SIZE, SIZE, values, dtype="uint16") for name, values in columns.items()]


def build_sar_scene(flooded: bool, reservoir_radius: float, seed: int) -> list[BandArray]:
    """Return VV and VH sigma0 in dB for one date, with multiplicative speckle.

    Speckle is drawn from a gamma distribution with four looks, the usual
    equivalent number of looks for Sentinel-1 GRD, so the scene is as noisy as
    a real one and the speckle filter has something to do.
    """
    rng = random.Random(seed)
    looks = 4.0
    vv: list[float] = []
    vh: list[float] = []

    for y in range(SIZE):
        for x in range(SIZE):
            vigour = max(0.0, min(1.0, _terrain(x, y)))

            water = (
                _is_river(x, y)
                or _is_reservoir(x, y, reservoir_radius)
                or (flooded and _is_flooded(x, y) and not _is_town(x, y))
            )
            if water:
                # Specular reflection off smooth water: very dark.
                vv_db, vh_db = -22.0, -28.0
            elif _is_town(x, y):
                # Double bounce off walls and ground: very bright.
                vv_db, vh_db = -3.0, -10.0
            else:
                # Volume scattering rises with canopy density.
                vv_db, vh_db = -11.0 + 3.0 * vigour, -18.0 + 4.0 * vigour

            for target, level in ((vv, vv_db), (vh, vh_db)):
                power = 10.0 ** (level / 10.0) * rng.gammavariate(looks, 1.0 / looks)
                target.append(10.0 * math.log10(power))

    return [
        BandArray("VV", SIZE, SIZE, vv, dtype="float32"),
        BandArray("VH", SIZE, SIZE, vh, dtype="float32"),
    ]


def write_scene(
    path: str,
    bands: list[BandArray],
    acquired: str,
    sensor: str = "sentinel2",
    dtype: str = "uint16",
) -> None:
    metadata = {
        "band_names": [band.name for band in bands],
        "sensor": sensor,
        "acquisition_date": acquired,
    }
    write_raster(path, bands, GEOREFERENCE, dtype=dtype, metadata=metadata)
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
    write_scene(
        os.path.join(directory, "sar_2024-06-10.tif"),
        build_sar_scene(flooded=False, reservoir_radius=26, seed=610),
        "2024-06-10",
        sensor="sentinel1",
        dtype="float32",
    )
    write_scene(
        os.path.join(directory, "sar_2024-08-22.tif"),
        build_sar_scene(flooded=True, reservoir_radius=40, seed=822),
        "2024-08-22",
        sensor="sentinel1",
        dtype="float32",
    )
    write_scene(
        os.path.join(directory, "scene_2024-08-22_cloudy.tif"),
        build_flood_scene(),
        "2024-08-22",
    )
    print(
        "\nTry, with one optical scene:\n"
        "  'How healthy is the vegetation in this scene?'\n"
        "  'Classify the land cover in the north-west quadrant.'\n"
        "  'How many water bodies are there?'\n"
        "with both optical scenes:\n"
        "  'Compare these two dates and show me what changed.'\n"
        "with sar_2024-08-22.tif:\n"
        "  'Find areas affected by flooding.'\n"
        "with both SAR scenes:\n"
        "  'Compare these two radar images and show where flooding appeared.'\n"
        "with scene_2024-08-22_cloudy.tif and sar_2024-08-22.tif:\n"
        "  'Fuse the optical and radar images to map the flood.'"
    )


if __name__ == "__main__":
    main()
