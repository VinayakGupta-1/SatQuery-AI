"""Runtime configuration for the SatQuery backend.

Every value can be overridden by an environment variable, so the same code runs
from a developer machine, a test, and a deployment without edits.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field

ENV_PREFIX = "SATQUERY_"


def _load_dotenv_file() -> None:
    """Read ``backend/.env`` into the environment, if one exists.

    Without this, a ``.env`` file would sit there doing nothing and the only
    way to configure the service would be exporting variables by hand.

    A real environment variable always wins (``override=False``): a value set
    in the shell, a container or a CI job must not be silently replaced by a
    developer's local file.

    python-dotenv is optional. If it is missing, configuration still works
    through the environment, so this never becomes a hard dependency.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - only when the extra is absent
        return

    # backend/app/config/settings.py -> backend/.env
    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    load_dotenv(os.path.join(backend_root, ".env"), override=False)


_load_dotenv_file()

#: Raster extensions the API will accept as an upload. The list is deliberately
#: short: an upload is opened by the raster layer immediately, and anything it
#: cannot read is rejected at ingestion rather than deep inside a tool.
DEFAULT_ALLOWED_EXTENSIONS = (".tif", ".tiff", ".gtif", ".gtiff", ".jp2")


def _env(name: str, default: str) -> str:
    return os.environ.get(ENV_PREFIX + name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(ENV_PREFIX + name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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

    # ---- natural-language understanding ----------------------------
    #: Which query-understanding backend to use.
    #:
    #: ``auto``   -- use the hosted model when an API key is configured, and
    #:              the rule engine when it is not. This is the default, and
    #:              it is what makes the LLM switch itself off rather than
    #:              failing when no key is present.
    #: ``rules``  -- force the deterministic keyword classifier. No network,
    #:              no key, no cost. Always available.
    #: ``ollama`` -- a locally hosted open-weights model via Ollama. Free,
    #:              needs no key, but the user must run Ollama themselves.
    #: ``hosted`` -- force an OpenAI-compatible chat-completions endpoint.
    #:              Requires ``agent_api_key``.
    #:
    #: "hosted" is deliberately generic rather than tied to one vendor: Groq,
    #: OpenRouter and Google AI Studio all speak this protocol and all issue
    #: free-tier keys, so one adapter covers them without committing the
    #: project to a paid account.
    agent_provider: str = field(
        default_factory=lambda: _env("AGENT_PROVIDER", "auto").strip().lower()
    )
    #: Credential for the hosted provider. Absent by default -- and when it is
    #: absent under ``auto``, the hosted path is simply never taken.
    #:
    #: This value is secret. It is never logged, never returned by any
    #: endpoint, and never included in an error message.
    agent_api_key: str = field(
        default_factory=lambda: _env("AGENT_API_KEY", "").strip()
    )
    #: Model name passed to the local provider. Ignored by ``rules``.
    agent_model: str = field(
        default_factory=lambda: _env("AGENT_MODEL", "llama3.2")
    )
    #: Base URL of the local Ollama server. Never leaves the machine.
    agent_base_url: str = field(
        default_factory=lambda: _env("AGENT_BASE_URL", "http://localhost:11434")
    )
    #: Base URL of the hosted OpenAI-compatible endpoint. Defaults to Groq,
    #: whose free tier needs no payment details.
    agent_hosted_base_url: str = field(
        default_factory=lambda: _env(
            "AGENT_HOSTED_BASE_URL", "https://api.groq.com/openai/v1"
        ).rstrip("/")
    )
    #: Model id for the hosted provider.
    agent_hosted_model: str = field(
        default_factory=lambda: _env("AGENT_HOSTED_MODEL", "llama-3.3-70b-versatile")
    )
    #: How long to wait for the local model before falling back to rules.
    agent_timeout_seconds: int = field(
        default_factory=lambda: _env_int("AGENT_TIMEOUT_SECONDS", 30)
    )
    #: When true, a failing LLM provider falls back to the rule-based reader
    #: instead of failing the request. Keeping this on means an unreachable
    #: Ollama degrades the answer rather than breaking the service.
    agent_fallback_to_rules: bool = field(
        default_factory=lambda: _env_bool("AGENT_FALLBACK_TO_RULES", True)
    )

    # ---- observability ---------------------------------------------
    log_level: str = field(
        default_factory=lambda: _env("LOG_LEVEL", "INFO").strip().upper()
    )
    #: Emit one JSON object per log line. Useful when shipping to a collector;
    #: off by default because plain text is easier to read while developing.
    log_json: bool = field(default_factory=lambda: _env_bool("LOG_JSON", False))

    # ---- derived ----------------------------------------------------
    @property
    def has_agent_api_key(self) -> bool:
        """Whether a hosted-provider credential is configured."""
        return bool(self.agent_api_key)

    @property
    def resolved_agent_provider(self) -> str:
        """The provider that will actually be used.

        ``auto`` resolves to the hosted model when a key is present and to the
        rule engine when it is not, so removing the key switches the LLM off
        instead of breaking the service.
        """
        provider = (self.agent_provider or "auto").strip().lower()
        if provider != "auto":
            return provider
        return "hosted" if self.has_agent_api_key else "rules"

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
