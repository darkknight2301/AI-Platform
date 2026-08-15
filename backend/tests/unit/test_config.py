"""Unit tests for environment-driven configuration."""
from __future__ import annotations

from src.core.config import Environment, Settings


def test_default_environment_is_development_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.environment == Environment.DEVELOPMENT
    assert settings.is_production is False


def test_environment_overridable_via_constructor() -> None:
    settings = Settings(environment=Environment.PRODUCTION, _env_file=None)
    assert settings.is_production is True


def test_cors_origins_parsed_from_csv_string() -> None:
    settings = Settings(cors_allow_origins="https://a.example.com, https://b.example.com", _env_file=None)
    assert settings.cors_allow_origins == ["https://a.example.com", "https://b.example.com"]
