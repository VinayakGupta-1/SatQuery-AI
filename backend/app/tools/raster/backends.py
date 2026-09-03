"""Detection of the optional libraries the raster layer can take advantage of.

This lives apart from :mod:`app.tools.raster.io` so that low-level modules --
resampling, index arithmetic -- can ask what is available without importing the
I/O layer that in turn depends on them.
"""

from __future__ import annotations

import os
from typing import Any

#: Set to "builtin" to force the dependency-free backend even when rasterio is
#: installed. This exists so the test suite can prove both backends agree, and
#: so a deployment can fall back without uninstalling anything.
BACKEND_ENV_VAR = "SATQUERY_RASTER_BACKEND"


def has_rasterio() -> bool:
    """Return True when the rasterio backend is available and permitted."""
    if os.environ.get(BACKEND_ENV_VAR, "").strip().lower() == "builtin":
        return False
    try:
        import rasterio  # noqa: F401
    except Exception:
        return False
    return True


def has_numpy() -> bool:
    """Return True when numpy is importable (used to accelerate arithmetic)."""
    try:
        import numpy  # noqa: F401
    except Exception:
        return False
    return True


def active_backend() -> str:
    """Return the identifier of the backend that raster I/O will use."""
    return "rasterio" if has_rasterio() else "builtin"


def backend_report() -> dict[str, Any]:
    """Describe the active raster capabilities, for execution metadata."""
    return {
        "raster_backend": active_backend(),
        "numpy_available": has_numpy(),
        "supports_compressed_geotiff": has_rasterio(),
    }
