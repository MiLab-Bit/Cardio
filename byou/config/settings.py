"""Unified settings via pydantic-settings, loaded from .env.

All configuration lives here.  No scattered os.getenv / os.environ reads elsewhere.

Environment discovery:
  pydantic-settings searches for  .env  in the *current working directory*
  at the time Settings() is instantiated.  To ensure the project .env
  is found regardless of where the process was started, we:
    1. Walk up from cwd to find the nearest .env (up to 6 levels).
    2. Pass that path to  env_file=  so pydantic-settings reads it once.
  If no .env is found pydantic-settings falls back to the default value
  ("") and silently uses only os.environ / OS secrets (Azure, K8s, etc.).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ─────────────────────────────────────────────────────────────────
#  Env-file discovery  (runs at Settings() instantiation time)
# ─────────────────────────────────────────────────────────────────

# Package root — Z:/Dev/Byou/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


def _find_env_file() -> Path | None:
    """Walk up from cwd (and from the package root as fallback) to find .env.

    Stops after 6 upward steps from any start point to avoid scanning the
    entire filesystem on misconfigured setups.
    """
    search_roots: list[Path] = [Path.cwd().resolve()]

    # Also search from package root — useful when running via `python -m`
    # from a different working directory.
    if _PACKAGE_ROOT.exists():
        search_roots.append(_PACKAGE_ROOT)

    seen: set[Path] = set()

    for root in search_roots:
        current: Path = root
        for _ in range(8):          # up to 8 levels deep
            if current in seen:
                break
            seen.add(current)
            candidate = current / ".env"
            if candidate.is_file():
                return candidate
            parent = current.parent
            if parent == current:   # filesystem root reached
                break
            current = parent

    return None


# Compute once at module import so pydantic-settings sees a stable default.
# If the file doesn't exist yet pydantic-settings treats env_file="" gracefully.
_DEFAULT_ENV_FILE = str(_find_env_file() or "")


# ─────────────────────────────────────────────────────────────────
#  Settings
# ─────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """All Byou configuration values with sensible defaults.

    Load order (later entries override earlier ones):
      1. Hard-coded Field defaults below.
      2. OS environment variables (always active, highest priority).
      3. .env file (env_file), read once at instantiation.

    Tip: to force a fresh search for .env after the process has started
    (e.g. after a  chdir), call  reset_settings()  then access
    get_settings() again.
    """

    model_config = SettingsConfigDict(
        env_file=_DEFAULT_ENV_FILE,          # path found at import time
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,               # env vars like OPENAI_API_KEY work
    )

    # ── LLM ────────────────────────────────────────────────────
    openai_api_key: str = Field(default="sk-placeholder", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
    )
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_max_retries: int = Field(default=3, ge=1, le=10)

    # ── Model Tier Routing (v2) ─────────────────────────────────
    model_cheap: str = Field(
        default="gpt-3.5-turbo",
        alias="BYOU_MODEL_CHEAP",
    )
    model_medium: str = Field(
        default="gpt-4o-mini",
        alias="BYOU_MODEL_MEDIUM",
    )
    model_deep: str = Field(
        default="gpt-4o",
        alias="BYOU_MODEL_DEEP",
    )

    # ── Paths ──────────────────────────────────────────────────
    data_dir: Path = Field(default=Path("./data"))

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, v: Path | str | None) -> Path:
        if v is None:
            return Path("./data")
        p = Path(v).expanduser().resolve()
        # Silently create the directory so the app doesn't crash on a
        # missing data_dir — log a warning instead.
        if not p.exists():
            import logging
            logging.getLogger(__name__).warning(
                "data_dir %s does not exist — creating it.", p
            )
            p.mkdir(parents=True, exist_ok=True)
        return p

    # ── Runtime ────────────────────────────────────────────────
    max_concurrent_pipelines: int = Field(default=3, ge=1, le=20)
    pipeline_timeout_seconds: int = Field(default=300, ge=10, le=3600)

    # ── Security ───────────────────────────────────────────────
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)   # 10 MB
    upload_allowed_mime_types: list[str] = [
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/tiff",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/ogg",
        "audio/m4a",
        "audio/x-m4a",
    ]
    upload_allowed_extensions: list[str] = [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".tiff",
        ".tif",
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
    ]

    # ── Learning Loop ──────────────────────────────────────────
    learning_max_history: int = Field(default=100, ge=10, le=10000)
    learning_weight_step: float = Field(default=0.1, ge=0.0, le=1.0)

    # ── Logging ────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="BYOU_LOG_LEVEL")

    # ── CRM integration (optional) ─────────────────────────────
    crm_api_url: str = ""
    crm_api_key: str = ""
    crm_provider: str = Field(default="generic", alias="CRM_PROVIDER")
    crm_auto_push: bool = Field(default=True, alias="CRM_AUTO_PUSH")
    crm_auto_pull: bool = Field(default=False, alias="CRM_AUTO_PULL")
    crm_conflict_strategy: str = Field(default="newest_wins", alias="CRM_CONFLICT_STRATEGY")
    # Salesforce OAuth
    crm_oauth_client_id: str = Field(default="", alias="CRM_OAUTH_CLIENT_ID")
    crm_oauth_client_secret: str = Field(default="", alias="CRM_OAUTH_CLIENT_SECRET")
    crm_oauth_refresh_token: str = Field(default="", alias="CRM_OAUTH_REFRESH_TOKEN")

    # ── Web Search (Tavily) ────────────────────────────────────
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # ── Company Data APIs ──────────────────────────────────────
    opencorporates_api_key: str = Field(default="", alias="OPEN_CORPORATES_API_KEY")
    crunchbase_api_key: str = Field(default="", alias="CRUNCHBASE_API_KEY")
    serpapi_api_key: str = Field(default="", alias="SERPAPI_API_KEY")
    hunter_api_key: str = Field(default="", alias="HUNTER_API_KEY")
    clearbit_api_key: str = Field(default="", alias="CLEARBIT_API_KEY")
    google_vision_api_key: str = Field(default="", alias="GOOGLE_VISION_API_KEY")

    # ── API Security (Claw platform) ────────────────────────────
    master_api_key: str = Field(default="", alias="BYOU_MASTER_API_KEY")
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        alias="BYOU_CORS_ORIGINS",
    )

    # ── Free-mode (force free sources only) ─────────────────────
    force_free_sources: bool = Field(default=False, alias="BYOU_FORCE_FREE_SOURCES")
    """When True, skip all paid APIs (TianYanCha, Crunchbase, etc.)
    and rely only on free sources: Tavily, Wikipedia, website extract."""

    # ── Output ──────────────────────────────────────────────────
    output_dir: Path = Field(default=Path("./output"), alias="BYOU_OUTPUT_DIR")
    """Directory for generated reports (HTML, JSON, etc.)."""

    # ── Instance metadata ──────────────────────────────────────
    @property
    def env_file_used(self) -> str | None:
        """Return the .env path that was actually loaded, for diagnostics."""
        env = self.model_config.get("env_file", "")
        return env if env else None

    def __repr__(self) -> str:
        # Suppress the API key in repr output
        key = self.openai_api_key
        masked = f"{key[:8]}..." if len(key) > 8 else "***"
        return (
            f"<Settings env_file={self.env_file_used!r} "
            f"model_deep={self.model_deep!r} "
            f"openai_api_key={masked}>"
        )


# ─────────────────────────────────────────────────────────────────
#  Singleton with explicit reset
# ─────────────────────────────────────────────────────────────────

_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the global Settings singleton, creating it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Drop the global singleton so the next call to  get_settings()
    re-runs  _find_env_file()  and re-reads the .env file.

    Use this after a  chdir()  or when you want to pick up a newly
    created .env without restarting the process.
    """
    global _settings
    _settings = None


# Convenience alias — lazily initialised on first access.
# Prefer  get_settings()  in library code so reset_settings() works.
settings: Settings = get_settings()
