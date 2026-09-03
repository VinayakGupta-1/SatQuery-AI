"""NDBI -- Normalized Difference Built-up Index (Zha, Gao & Ni, 2003).

    NDBI = (SWIR - NIR) / (SWIR + NIR)

Built-up surfaces reflect shortwave infrared more than near-infrared, which
inverts the vegetation response and makes urban fabric stand out.

Note the band order: the published index puts SWIR in the positive role. The
opposite ordering, ``(NIR - SWIR)``, computes NDMI/NDWI-Gao (a moisture index)
and yields NDBI negated, so the sign convention matters when thresholding.
"""

from __future__ import annotations

from app.tools.indices.index_tool import NormalizedDifferenceIndexTool
from app.tools.indices.spec import IndexSpec

NDBI_SPEC = IndexSpec(
    name="NDBI",
    positive_parameter="swir_band",
    negative_parameter="nir_band",
    default_positive_band="swir1",
    default_negative_band="nir",
    interpretation_ranges=[
        ("non_built_up", -1.0, 0.0),
        ("possible_built_up", 0.0, 0.1),
        ("built_up", 0.1, 1.0),
    ],
    interpretation_note=(
        "Positive NDBI indicates built-up or bare impervious surfaces. Bare soil "
        "also scores positively, so NDBI is normally read alongside NDVI."
    ),
)


class NDBITool(NormalizedDifferenceIndexTool):
    """Computes NDBI from an optical multispectral raster."""

    tool_id = "ndbi"
    spec = NDBI_SPEC
