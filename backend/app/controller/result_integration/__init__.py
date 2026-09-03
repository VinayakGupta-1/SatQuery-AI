"""Stage 10 -- unification of tool output into a single result contract."""

from app.controller.result_integration.integrator import ResultIntegrator
from app.controller.result_integration.narrators import (
    NARRATORS,
    ChangeMapNarrator,
    RasterIndexNarrator,
    ResultNarrator,
    format_area,
    get_narrator,
    is_projected_crs,
)

__all__ = [
    "NARRATORS",
    "ChangeMapNarrator",
    "RasterIndexNarrator",
    "ResultIntegrator",
    "ResultNarrator",
    "format_area",
    "get_narrator",
    "is_projected_crs",
]
