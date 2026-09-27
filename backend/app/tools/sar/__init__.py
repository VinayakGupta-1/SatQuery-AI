"""Synthetic aperture radar analysis.

Nothing is imported here on purpose: the backscatter arithmetic is used by the
raster renderer, which the tools themselves depend on, so importing the tool
from the package would close an import cycle. Import
:mod:`app.tools.sar.tool` and :mod:`app.tools.sar.backscatter` directly.
"""
