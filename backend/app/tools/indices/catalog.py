"""The indices any tool may compute, keyed by identifier.

Change detection reads this catalogue to decide which index to difference
between two dates, so adding an index makes it available to that tool too.
"""

from __future__ import annotations

from app.tools.indices.ndbi import NDBI_SPEC
from app.tools.indices.ndvi import NDVI_SPEC
from app.tools.indices.ndwi import NDWI_SPEC
from app.tools.indices.spec import IndexSpec

INDEX_SPECS: dict[str, IndexSpec] = {
    "ndvi": NDVI_SPEC,
    "ndwi": NDWI_SPEC,
    "ndbi": NDBI_SPEC,
}


def get_index_spec(index: str) -> IndexSpec | None:
    """Return the spec for ``index``, or ``None`` when it is not catalogued."""
    return INDEX_SPECS.get(str(index).strip().lower())


def available_indices() -> list[str]:
    return sorted(INDEX_SPECS)
