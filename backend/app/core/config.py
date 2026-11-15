"""Application settings, loaded from the environment.

Secrets are never hard-coded. Anything sensitive comes from ``.env`` (ignored
by git) or from the deployment platform's environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- application ---
    app_name: str = "WealthOS"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)
    api_v1_prefix: str = "/api/v1"

    # --- database ---
    database_url: str = Field(
        default="postgresql+psycopg://localhost:5432/wealthos",
        alias="DATABASE_URL",
    )

    # --- auth ---
    jwt_secret_key: str = Field(default="insecure-development-key", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # --- Wealth Copilot ---
    # With no key the Copilot falls back to a deterministic explainer over the
    # same backend tool outputs, so the platform stays usable.
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    copilot_model: str = Field(default="claude-sonnet-5-5", alias="COPILOT_MODEL")

    # --- CORS ---
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # --- paths ---
    project_root: Path = PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def model_dir(self) -> Path:
        return self.project_root / "ml" / "models"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def reference_dir(self) -> Path:
        return self.data_dir / "reference"

    @property
    def copilot_enabled(self) -> bool:
        """True when a real LLM is reachable; otherwise the fallback is used."""
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance, so the .env file is parsed once per process."""
    return Settings()


settings = get_settings()
