"""Runtime configuration for CyEM Monitor. Everything comes from the environment
so the compose file is the single place to change behaviour."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("CYEM_DATA_DIR", "/data")))
    app_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    port: int = field(default_factory=lambda: _int("CYEM_PORT", 8080))
    tz: str = field(default_factory=lambda: _env("TZ", "Europe/London"))
    user_agent: str = field(default_factory=lambda: _env(
        "CYEM_USER_AGENT", "CyEM-Monitor/0.1 (self-hosted; personal situational awareness)"))
    http_timeout: int = field(default_factory=lambda: _int("HTTP_TIMEOUT", 40))
    collect_on_start: bool = field(default_factory=lambda: _bool("COLLECT_ON_START", True))
    retention_days: int = field(default_factory=lambda: _int("RETENTION_DAYS", 120))

    # Ollama
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://ollama:11434").rstrip("/"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen3.5:4b"))
    ollama_think: bool = field(default_factory=lambda: _bool("OLLAMA_THINK", False))
    ollama_num_ctx: int = field(default_factory=lambda: _int("OLLAMA_NUM_CTX", 8192))
    ollama_timeout: int = field(default_factory=lambda: _int("OLLAMA_TIMEOUT", 900))
    brief_hours: list[int] = field(default_factory=lambda: sorted({
        int(h) for h in _env("BRIEF_HOURS", "06,12,18,00").replace(";", ",").split(",") if h.strip().isdigit()}))
    brief_enabled: bool = field(default_factory=lambda: _bool("BRIEF_ENABLED", True))

    # Optional API keys (features degrade gracefully without them)
    cloudflare_token: str = field(default_factory=lambda: _env("CLOUDFLARE_API_TOKEN"))
    nvd_api_key: str = field(default_factory=lambda: _env("NVD_API_KEY"))
    abusech_auth_key: str = field(default_factory=lambda: _env("ABUSECH_AUTH_KEY"))
    opencti_url: str = field(default_factory=lambda: _env("OPENCTI_URL").rstrip("/"))
    opencti_token: str = field(default_factory=lambda: _env("OPENCTI_TOKEN"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cyem.sqlite3"

    @property
    def static_dir(self) -> Path:
        return self.app_dir / "static"

    @property
    def ref_dir(self) -> Path:
        return self.app_dir / "data"


settings = Settings()
