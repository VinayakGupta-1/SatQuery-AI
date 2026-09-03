"""NDWI -- Normalized Difference Water Index (McFeeters, 1996).

    NDWI = (Green - NIR) / (Green + NIR)

Water absorbs near-infrared strongly while still reflecting green, so open
water separates clearly from vegetation and soil.
"""

from __future__ import annotations

from app.tools.indices.index_tool import NormalizedDifferenceIndexTool
from app.tools.indices.spec import IndexSpec

NDWI_SPEC = IndexSpec(
    name="NDWI",
    positive_parameter="green_band",
    negative_parameter="nir_band",
    default_positive_band="green",
    default_negative_band="nir",
    interpretation_ranges=[
        ("non_water", -1.0, 0.0),
        ("possible_water", 0.0, 0.2),
        ("water", 0.2, 1.0),
    ],
    interpretation_note=(
        "Positive NDWI indicates surface water. McFeeters' threshold of zero "
        "separates water from land, though built-up surfaces can raise NDWI and "
        "are better isolated with a built-up index."
    ),
)


class NDWITool(NormalizedDifferenceIndexTool):
    """Computes NDWI from an optical multispectral raster."""

    tool_id = "ndwi"
    spec = NDWI_SPEC
