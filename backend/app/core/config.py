"""Application settings, loaded from the environment.

Secrets are never hard-coded. Anything sensitive comes from ``.env`` (ignored
by git) or from the deployment platform's environment.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Force the psycopg v3 driver onto a driverless PostgreSQL URL.

        Hosting platforms hand out ``postgresql://`` (Render, Neon) or the
        older ``postgres://`` (Heroku-style). SQLAlchemy reads a bare
        ``postgresql://`` as psycopg2, which this project does not install --
        only psycopg v3 -- so the first database call dies with
        ModuleNotFoundError. ``postgres://`` is not a dialect SQLAlchemy knows
        at all and raises on load.

        Rewriting here covers the app and Alembic together, since
        ``alembic/env.py`` takes its URL from these settings. An explicit
        driver (``postgresql+asyncpg://``, say) is left untouched.
        """
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    # --- auth ---
    jwt_secret_key: str = Field(default="insecure-development-key", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # --- Wealth Copilot (the AI chat) ---
    # Two providers sit behind one interface (app/services/llm). LLM_PROVIDER
    # "auto" uses Gemini when GEMINI_API_KEY is set, else Claude when
    # ANTHROPIC_API_KEY is set. With neither, the Copilot falls back to a
    # deterministic explainer over the same tool outputs, so the platform
    # stays usable.
    llm_provider: str = Field(default="auto", alias="LLM_PROVIDER")
    # Low-memory hosting (Render's free 512 MB). PyTorch is never loaded, so
    # the neural models (anomaly autoencoder, LSTM/GRU forecasts, the deep
    # swing models in the forward test) are off; LightGBM, HAR and the HMM
    # still serve model picks, Autopilot and the regime. Models load on first
    # use instead of at start-up.
    low_memory: bool = Field(default=False, alias="LOW_MEMORY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    copilot_model: str = Field(default="claude-opus-5-5", alias="COPILOT_MODEL")

    # --- live market data ---
    # Delayed quotes and intraday candles come from Yahoo Finance. Off, every
    # price comes from the seeded simulator instead -- the test suite runs
    # that way, so it never touches the network.
    live_market_enabled: bool = Field(default=True, alias="LIVE_MARKET_ENABLED")
    quote_ttl_seconds: float = Field(default=15.0, alias="QUOTE_TTL_SECONDS")

    # --- brokers (Upstox) ---
    # Where Upstox sends the browser after login. Must equal the redirect URL
    # registered on the user's Upstox developer app.
    upstox_redirect_uri: str = Field(
        default="http://localhost:8010/api/v1/brokers/upstox/callback", alias="UPSTOX_REDIRECT_URI")
    # Where the callback returns the user afterwards.
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")
    # The simulated broker from the account-linking phase. Off everywhere
    # except the test suite, which uses it to exercise the sync layer.
    broker_sandbox_enabled: bool = Field(default=False, alias="BROKER_SANDBOX_ENABLED")

    # --- paper trading ---
    paper_starting_cash: float = Field(default=1_000_000.0, alias="PAPER_STARTING_CASH")

    # --- CORS ---
    # NoDecode keeps pydantic-settings from JSON-decoding the env var before
    # validation. Without it, CORS_ORIGINS=https://wealthos.vercel.app is a
    # SettingsError at boot and the whole API fails to start -- which is the
    # exact value a deployment runbook tells you to set.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=[
            "http://localhost:3000", "http://127.0.0.1:3000",
            "http://localhost:3001", "http://127.0.0.1:3001",
        ],
        alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        """Accept a JSON array, a comma-separated list, or a single origin.

        Deployment platforms hand out plain strings, so all three forms have to
        work. An empty value means "no cross-origin callers", not "all".
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [origin.strip() for origin in text.split(",") if origin.strip()]

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
    def llm_provider_active(self) -> str | None:
        """'gemini', 'anthropic', or None (template fallback)."""
        choice = (self.llm_provider or "auto").strip().lower()
        has_gemini = bool(self.gemini_api_key.strip())
        has_claude = bool(self.anthropic_api_key.strip())
        if choice == "off":
            return None
        if choice == "gemini":
            return "gemini" if has_gemini else None
        if choice == "anthropic":
            return "anthropic" if has_claude else None
        return "gemini" if has_gemini else "anthropic" if has_claude else None

    @property
    def llm_model(self) -> str | None:
        provider = self.llm_provider_active
        return {"gemini": self.gemini_model, "anthropic": self.copilot_model}.get(provider or "")

    @property
    def copilot_enabled(self) -> bool:
        """True when a real LLM is configured; otherwise the fallback is used."""
        return self.llm_provider_active is not None


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance, so the .env file is parsed once per process."""
    return Settings()


settings = get_settings()
