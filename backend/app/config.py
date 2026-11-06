"""Application configuration, loaded from environment variables and the root .env file."""
from __future__ import annotations

import base64
import json
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"  # development | test | production

    # Secrets. In development they are generated once and stored under the data directory.
    # In production they must be provided explicitly.
    secret_key: str = ""
    encryption_key: str = ""

    # Database and storage
    database_url: str = ""
    data_dir: str = ""

    # Sessions and browser access
    session_ttl_hours: int = 72
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    public_app_url: str = "http://127.0.0.1:8000"

    # Resource limits
    max_upload_mb: int = 100
    max_rows: int = 2_000_000
    max_columns: int = 500
    max_page_size: int = 500
    query_timeout_seconds: int = 30
    query_memory_limit: str = "1GB"
    ingest_timeout_seconds: int = 600
    job_workers: int = 2

    # Rate limits (requests per minute, per client)
    rate_limit_auth_per_minute: int = 20
    rate_limit_ai_per_minute: int = 30
    rate_limit_upload_per_minute: int = 30

    # AI providers. "auto" selects the first provider with a key, otherwise demonstration mode.
    ai_provider: str = "auto"  # auto | demo | anthropic | openai | gemini
    ai_timeout_seconds: int = 60
    ai_share_category_values: bool = True
    ai_max_context_turns: int = 6
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: str = ""
    openai_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = ""

    # External data connections
    allow_private_connections: bool = False
    connection_timeout_seconds: int = 20
    connection_max_rows: int = 200_000
    connection_max_response_mb: int = 50

    # Optional e-mail delivery for password resets
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    frontend_dist: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir) if self.data_dir else REPO_ROOT / "data"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_path / 'dataforge.db').as_posix()}"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def frontend_dist_path(self) -> Path:
        return Path(self.frontend_dist) if self.frontend_dist else REPO_ROOT / "frontend" / "dist"


def _load_or_create_local_secrets(path: Path) -> dict[str, str]:
    """Create development-only secrets once, so sessions and encrypted values survive restarts."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "secret_key": secrets.token_urlsafe(48),
        "encryption_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    }
    path.write_text(json.dumps(values), encoding="utf-8")
    return values


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key or not settings.encryption_key:
        if settings.is_production:
            raise RuntimeError("SECRET_KEY and ENCRYPTION_KEY must be set in production.")
        local = _load_or_create_local_secrets(settings.data_path / ".local_secrets.json")
        settings.secret_key = settings.secret_key or local["secret_key"]
        settings.encryption_key = settings.encryption_key or local["encryption_key"]
    if settings.is_production:
        settings.cookie_secure = True  # session cookies must never travel over plain HTTP in production
    return settings
