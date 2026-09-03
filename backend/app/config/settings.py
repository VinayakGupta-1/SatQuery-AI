"""Runtime configuration for the SatQuery backend.

Every value can be overridden by an environment variable, so the same code runs
from a developer machine, a test, and a deployment without edits.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

ENV_PREFIX = "SATQUERY_"

#: Raster extensions the API will accept as an upload. The list is deliberately
#: short: an upload is opened by the raster layer immediately, and anything it
#: cannot read is rejected at ingestion rather than deep inside a tool.
DEFAULT_ALLOWED_EXTENSIONS = (".tif", ".tiff", ".gtif", ".gtiff", ".jp2")


def _env(name: str, default: str) -> str:
    return os.environ.get(ENV_PREFIX + name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Resolved configuration for one process."""

    storage_root: str = field(
        default_factory=lambda: _env(
            "STORAGE_ROOT", os.path.join(tempfile.gettempdir(), "satquery")
        )
    )
    #: Uploads larger than this are refused before being written to disk.
    max_upload_bytes: int = field(
        default_factory=lambda: _env_int("MAX_UPLOAD_BYTES", 512 * 1024 * 1024)
    )
    max_images_per_task: int = field(
        default_factory=lambda: _env_int("MAX_IMAGES_PER_TASK", 8)
    )
    allowed_extensions: tuple[str, ...] = DEFAULT_ALLOWED_EXTENSIONS

    #: Browser origins permitted to call the API. The default suits a local
    #: React dev server; set SATQUERY_CORS_ORIGINS to a comma-separated list
    #: in deployment rather than widening this to "*".
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in _env(
                "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
            ).split(",")
            if origin.strip()
        )
    )

    @property
    def upload_directory(self) -> str:
        return os.path.join(self.storage_root, "uploads")

    @property
    def output_directory(self) -> str:
        return os.path.join(self.storage_root, "outputs")

    def prepare(self) -> "Settings":
        """Create the storage directories this process will write to."""
        os.makedirs(self.upload_directory, exist_ok=True)
        os.makedirs(self.output_directory, exist_ok=True)
        return self

    def task_upload_directory(self, task_id: str) -> str:
        return os.path.join(self.upload_directory, task_id)

    def task_output_directory(self, task_id: str) -> str:
        return os.path.join(self.output_directory, task_id)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings, creating them on first use."""
    global _settings
    if _settings is None:
        _settings = Settings().prepare()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings so the next call re-reads the environment."""
    global _settings
    _settings = None
