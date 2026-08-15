"""
Environment-driven application configuration.

Settings are loaded from environment variables (optionally via a local
.env file during development). No secrets are hardcoded here — see
.env.example for the list of variables an operator must supply.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """Central application configuration.

    All values are sourced from environment variables. Defaults are only
    provided where they are safe for local development; production
    deployments are expected to override every security-sensitive value.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core -----------------------------------------------------------
    app_name: str = "AI Platform API"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Security ---------------------------------------------------------
    # Must be overridden via environment variable in every non-local
    # deployment. Never commit a real value.
    secret_key: str = Field(default="CHANGE_ME_IN_ENV", repr=False)
    access_token_expire_minutes: int = 30
    algorithm: str = "HS256"

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://app_user:app_password@localhost:5432/app_db",
        description="SQLAlchemy async connection string.",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # --- CORS ---------------------------------------------------------------
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    # --- Rate limiting / concurrency (foundation only, enforced later) ----
    rate_limit_requests_per_minute: int = 60

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_csv(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached because Settings parses the environment on construction;
    repeated instantiation across the app would be wasteful. Tests can
    call `get_settings.cache_clear()` to force a reload.
    """
    return Settings()
