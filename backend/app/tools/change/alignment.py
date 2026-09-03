"""Geometric and temporal alignment checks for bi-temporal analysis.

Comparing two dates is only meaningful when pixel *(row, column)* refers to the
same patch of ground in both images. Nothing downstream can detect a violation
of that: a misaligned pair produces a confident, plausible, and completely
wrong change map. So the check happens here, before any arithmetic, and it
refuses rather than resampling -- silently reprojecting a user's imagery would
hide a problem they need to know about.
"""

from __future__ import annotations

from datetime import date

from app.tools.base import ToolExecutionError
from app.tools.raster.inspection import find_acquisition_date
from app.tools.raster.model import RasterDataset

#: Pixel sizes must agree to this relative tolerance.
PIXEL_SIZE_TOLERANCE = 1e-6

#: Origins may differ by at most this fraction of a pixel before the grids are
#: considered offset from one another.
ORIGIN_TOLERANCE_PIXELS = 0.5


def require_aligned(first: RasterDataset, second: RasterDataset) -> None:
    """Raise unless the two datasets share one pixel grid."""
    if (first.width, first.height) != (second.width, second.height):
        raise ToolExecutionError(
            f"The two images have different dimensions ({first.width}x{first.height} "
            f"and {second.width}x{second.height}). Bi-temporal analysis requires a "
            "co-registered pair on an identical grid; resample them first."
        )

    first_crs = first.georeference.crs
    second_crs = second.georeference.crs
    if first_crs and second_crs and first_crs != second_crs:
        raise ToolExecutionError(
            f"The two images use different coordinate reference systems "
            f"({first_crs} and {second_crs}). Reproject them to a common CRS "
            "before comparing them."
        )

    first_transform = first.georeference.transform
    second_transform = second.georeference.transform
    if first_transform is None or second_transform is None:
        # Without georeferencing we cannot prove alignment. Dimensions match,
        # so proceed, but this is the one case where alignment is assumed.
        return

    _require_same_pixel_size(first_transform, second_transform)
    _require_same_origin(first_transform, second_transform)


def _require_same_pixel_size(first, second) -> None:
    for index, axis in ((1, "width"), (5, "height")):
        a, b = abs(first[index]), abs(second[index])
        if a == 0 or b == 0:
            raise ToolExecutionError("A raster reports a zero pixel size.")
        if abs(a - b) / max(a, b) > PIXEL_SIZE_TOLERANCE:
            raise ToolExecutionError(
                f"The two images have different pixel {axis}s ({a} and {b}). "
                "Resample them to a common resolution before comparing them."
            )


def _require_same_origin(first, second) -> None:
    pixel_width, pixel_height = abs(first[1]), abs(first[5])
    offset_x = abs(first[0] - second[0]) / pixel_width
    offset_y = abs(first[3] - second[3]) / pixel_height

    if offset_x > ORIGIN_TOLERANCE_PIXELS or offset_y > ORIGIN_TOLERANCE_PIXELS:
        raise ToolExecutionError(
            f"The two images are offset by ({offset_x:.2f}, {offset_y:.2f}) pixels. "
            "A bi-temporal comparison needs them co-registered to within half a "
            "pixel; align them before comparing."
        )


def order_by_acquisition(
    first: RasterDataset,
    second: RasterDataset,
) -> tuple[RasterDataset, RasterDataset, dict[str, object]]:
    """Return the pair as ``(earlier, later)`` plus how that was decided.

    Ordering by upload position would invert the sign of every change when a
    user happens to supply the later image first, so acquisition dates are used
    whenever the files carry them. When they do not, input order is assumed and
    the output says so rather than implying a certainty it does not have.
    """
    first_date = find_acquisition_date(first)
    second_date = find_acquisition_date(second)

    if isinstance(first_date, date) and isinstance(second_date, date):
        if first_date == second_date:
            raise ToolExecutionError(
                f"Both images report the same acquisition date ({first_date}); "
                "a change comparison needs two different dates."
            )
        earlier, later = (
            (first, second) if first_date < second_date else (second, first)
        )
        return earlier, later, {
            "temporal_order_source": "acquisition_date",
            "earlier_date": min(first_date, second_date).isoformat(),
            "later_date": max(first_date, second_date).isoformat(),
        }

    return first, second, {
        "temporal_order_source": "input_order",
        "earlier_date": first_date.isoformat() if first_date else None,
        "later_date": second_date.isoformat() if second_date else None,
        "note": (
            "Acquisition dates were not available in both rasters, so the input "
            "order was assumed to be earliest first. The sign of the reported "
            "change depends on that assumption."
        ),
    }
