"""NDVI -- Normalized Difference Vegetation Index (Rouse et al., 1974).

    NDVI = (NIR - Red) / (NIR + Red)

Healthy vegetation reflects strongly in the near-infrared and absorbs red light
for photosynthesis, so the index rises with vegetation vigour and density.
"""

from __future__ import annotations

from app.tools.indices.index_tool import NormalizedDifferenceIndexTool
from app.tools.indices.spec import IndexSpec

NDVI_SPEC = IndexSpec(
    name="NDVI",
    positive_parameter="nir_band",
    negative_parameter="red_band",
    default_positive_band="nir",
    default_negative_band="red",
    # Conventional NDVI interpretation breakpoints.
    interpretation_ranges=[
        ("water_or_non_vegetated", -1.0, 0.0),
        ("bare_soil_or_built_up", 0.0, 0.2),
        ("sparse_vegetation", 0.2, 0.4),
        ("moderate_vegetation", 0.4, 0.6),
        ("dense_vegetation", 0.6, 1.0),
    ],
    interpretation_note=(
        "Higher NDVI indicates denser, healthier vegetation. Values at or below "
        "zero usually correspond to water, bare ground, or built-up surfaces."
    ),
)


class NDVITool(NormalizedDifferenceIndexTool):
    """Computes NDVI from an optical multispectral raster."""

    tool_id = "ndvi"
    spec = NDVI_SPEC
