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

    ``SATQUERY_LOAD_DOTENV=0`` skips the file entirely. The test suite sets it,
    because a developer's ``.env`` usually holds a real API key, and tests that
    silently pick it up stop being reproducible and start spending quota.
    """
    if os.environ.get(ENV_PREFIX + "LOAD_DOTENV", "1").strip().lower() in {
        "0", "false", "no", "off",
    }:
        return
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
    #: At startup, task files older than this are deleted: the task list lives
    #: in memory, so nothing from an earlier process can be served again. 0
    #: keeps everything.
    retention_hours: int = field(default_factory=lambda: _env_int("RETENTION_HOURS", 24))
    #: A built workspace (``frontend/dist``) to serve from this process, for
    #: single-container deployments with no nginx in front. Empty serves the
    #: API only.
    frontend_dist: str = field(default_factory=lambda: _env("FRONTEND_DIST", "").strip())
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
    #: Model id for the hosted provider. Groq retires models; this is one it
    #: served in September 2026 that returns reliable JSON plans.
    agent_hosted_model: str = field(
        default_factory=lambda: _env("AGENT_HOSTED_MODEL", "openai/gpt-oss-120b")
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

    # ---- satellite visual question answering -----------------------
    #: VQA sends a rendered preview of the user's imagery to the hosted vision
    #: model. That discloses the imagery to a third party, which is a different
    #: decision from sending a sentence for query understanding -- so having an
    #: API key is not enough, and VQA stays off until an operator turns it on.
    vqa_enabled: bool = field(default_factory=lambda: _env_bool("VQA_ENABLED", False))
    #: Which vision-language model serves the VLM core:
    #:
    #: ``hosted`` -- any OpenAI-compatible endpoint (Groq by default, or a
    #:              fine-tuned model served by vLLM or TGI). Needs the API key,
    #:              and the rendered preview leaves the machine.
    #: ``ollama`` -- a vision model on this machine through Ollama, e.g.
    #:              ``llama3.2-vision`` or a fine-tuned model imported into it.
    #:              No key, and nothing leaves the machine.
    vqa_provider: str = field(
        default_factory=lambda: _env("VQA_PROVIDER", "hosted").strip().lower()
    )
    #: A vision-capable model id. Empty means the provider's default.
    vqa_model: str = field(default_factory=lambda: _env("VQA_MODEL", "").strip())
    #: The endpoint for the VLM core. Empty means the provider's default: the
    #: query-understanding endpoint when hosted, the local Ollama server when not.
    vqa_base_url: str = field(
        default_factory=lambda: _env("VQA_BASE_URL", "").strip().rstrip("/")
    )
    vqa_timeout_seconds: int = field(
        default_factory=lambda: _env_int("VQA_TIMEOUT_SECONDS", 60)
    )
    #: A benchmark report written by scripts/evaluate_benchmark.py. When it
    #: covers the configured model, its measured accuracy becomes part of the
    #: confidence reported with every answer that model gives.
    vqa_benchmark_report: str = field(
        default_factory=lambda: _env("VQA_BENCHMARK_REPORT", "").strip()
    )
    #: A key for SATQUERY_VQA_BASE_URL when that endpoint needs its own. The
    #: query-understanding key is never sent to an endpoint other than the one
    #: it was issued for.
    vqa_api_key: str = field(default_factory=lambda: _env("VQA_API_KEY", "").strip())

    # ---- users -----------------------------------------------------
    #: A Supabase project for sign-up, email verification and sign-in. When it
    #: is set, every analysis request must carry a valid Supabase access token
    #: and each user's results are kept in that project's ``analyses`` table.
    #: Unset, the API is open and the workspace opens sessions locally.
    supabase_url: str = field(
        default_factory=lambda: _env("SUPABASE_URL", "").strip().rstrip("/")
    )
    #: The project's publishable (or legacy anon) key. Public by design: it
    #: identifies the project, and row level security decides what it can do.
    supabase_publishable_key: str = field(
        default_factory=lambda: _env("SUPABASE_PUBLISHABLE_KEY", "").strip()
    )

    # ---- automatic imagery acquisition -------------------------------
    #: When a request arrives without imagery, find and download a scene for
    #: the place the question names. Sentinel-2 L2A (optical) and Sentinel-1
    #: RTC (radar) come from Microsoft Planetary Computer, which needs no
    #: account; place names are resolved by OpenStreetMap's Nominatim. Turn it
    #: off where the server must not reach the internet.
    fetch_enabled: bool = field(default_factory=lambda: _env_bool("FETCH_ENABLED", True))
    fetch_stac_url: str = field(
        default_factory=lambda: _env(
            "FETCH_STAC_URL", "https://planetarycomputer.microsoft.com/api/stac/v1"
        ).rstrip("/")
    )
    #: Planetary Computer serves its files through short-lived read tokens,
    #: issued anonymously per collection.
    fetch_token_url: str = field(
        default_factory=lambda: _env(
            "FETCH_TOKEN_URL", "https://planetarycomputer.microsoft.com/api/sas/v1/token"
        ).rstrip("/")
    )
    geocoder_url: str = field(
        default_factory=lambda: _env(
            "GEOCODER_URL", "https://nominatim.openstreetmap.org/search"
        )
    )
    #: Asked when Nominatim refuses or cannot be reached. Nominatim limits
    #: requests per IP address, and a cloud host's shared address is often
    #: over that limit. Photon searches the same OpenStreetMap data and needs
    #: no account. Empty disables the fallback.
    geocoder_fallback_url: str = field(
        default_factory=lambda: _env(
            "GEOCODER_FALLBACK_URL", "https://photon.komoot.io/api/"
        ).strip()
    )
    #: Side of the square fetched around a point (a pair of coordinates, or a
    #: geocoded place too small to analyse on its own), in kilometres.
    fetch_default_extent_km: int = field(
        default_factory=lambda: _env_int("FETCH_DEFAULT_EXTENT_KM", 10)
    )
    #: Largest side fetched. A larger place -- a district, a state -- is cut to
    #: a square of this size around its centre, and the answer says so.
    fetch_max_extent_km: int = field(
        default_factory=lambda: _env_int("FETCH_MAX_EXTENT_KM", 20)
    )
    #: Longest side of a fetched image in pixels. Larger areas are read from
    #: the files' overviews at 20, 40 or 80 m rather than at 10 m. Download
    #: time grows with the square of this, and is what a fetch spends most of.
    fetch_max_pixels: int = field(default_factory=lambda: _env_int("FETCH_MAX_PIXELS", 1024))
    #: Catalogue tiles cloudier than this are not considered at all.
    fetch_max_cloud_percent: int = field(
        default_factory=lambda: _env_int("FETCH_MAX_CLOUD_PERCENT", 60)
    )
    #: How far back "now" reaches when a question names no date.
    fetch_lookback_days: int = field(default_factory=lambda: _env_int("FETCH_LOOKBACK_DAYS", 120))
    fetch_timeout_seconds: int = field(
        default_factory=lambda: _env_int("FETCH_TIMEOUT_SECONDS", 60)
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
    def auth_enabled(self) -> bool:
        """Whether requests must come from a signed-in Supabase user."""
        return bool(self.supabase_url and self.supabase_publishable_key)

    @property
    def vqa_is_local(self) -> bool:
        """Whether the vision model runs on this machine."""
        return self.vqa_provider == "ollama"

    @property
    def resolved_vqa_base_url(self) -> str:
        if self.vqa_base_url:
            return self.vqa_base_url
        return self.agent_base_url.rstrip("/") if self.vqa_is_local else self.agent_hosted_base_url

    @property
    def resolved_vqa_model(self) -> str:
        if self.vqa_model:
            return self.vqa_model
        # The hosted default is the vision model Groq served in September
        # 2026; when Groq retires it, set SATQUERY_VQA_MODEL.
        return "llama3.2-vision" if self.vqa_is_local else "qwen/qwen3.8-27b"

    @property
    def vqa_uses_agent_endpoint(self) -> bool:
        """Whether the VLM is served by the same hosted endpoint as query understanding."""
        if self.vqa_is_local:
            return False
        return not self.vqa_base_url or self.vqa_base_url == self.agent_hosted_base_url.rstrip("/")

    @property
    def resolved_vqa_api_key(self) -> str:
        """The key sent to the VLM endpoint.

        Its own key when one is set; otherwise the query-understanding key,
        but only to the endpoint that key belongs to. A self-hosted model --
        the fine-tuned one, say -- is never handed the Groq key.
        """
        if self.vqa_api_key:
            return self.vqa_api_key
        return self.agent_api_key if self.vqa_uses_agent_endpoint else ""

    @property
    def vqa_available(self) -> bool:
        """The VLM core runs only when an operator enabled it -- and, on the
        shared hosted endpoint, a key is present. A local model or a
        self-hosted endpoint may need none."""
        if not self.vqa_enabled or self.vqa_provider not in {"hosted", "ollama"}:
            return False
        return not self.vqa_uses_agent_endpoint or bool(self.resolved_vqa_api_key)

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
