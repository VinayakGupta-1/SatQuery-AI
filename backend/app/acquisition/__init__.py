"""Automatic imagery acquisition: a place and a question in, scenes out.

When a request arrives without imagery, this package finds the place the
question names, picks Sentinel-2 or Sentinel-1 scenes for the task and period,
downloads only the area's pixels from Microsoft Planetary Computer, and writes
them as GeoTIFFs the rest of the pipeline treats exactly like uploads.
"""

from app.acquisition.service import AcquisitionOutcome, FetchedImage, acquire
from app.acquisition.web import AcquisitionError

__all__ = ["AcquisitionError", "AcquisitionOutcome", "FetchedImage", "acquire"]
