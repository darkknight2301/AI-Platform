"""YAML configuration: loading, ``${ENV_VAR}`` expansion and validation."""

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised for a missing, malformed or incomplete configuration file."""


@dataclass
class RedmineCfg:
    """Redmine REST API access."""
    url: str = ""
    api_key: str = ""
    timeout: float = 30.0
    verify_ssl: bool = True
    page_size: int = 100


@dataclass
class GitCfg:
    """Git project URL used to turn bare ``!123`` / commit / branch references into links."""
    base_url: str = ""


@dataclass
class LlmCfg:
    """Local LLM endpoint and deterministic generation settings."""
    backend: str = "ollama"
    endpoint: str = "http://localhost:11434"
    model: str = "qwen3:27b"
    num_ctx: int = 16384
    max_output_tokens: int = 3000
    seed: int = 42
    timeout: float = 900.0
    think: bool | None = None  # None = do not send the option


@dataclass
class TranslateCfg:
    """Translation through ``<module>.translate(text) -> str``."""
    enabled: bool = True
    module: str = "api"
    include_original: bool = True


@dataclass
class AnalysisCfg:
    """Ticket graph traversal and context limits."""
    max_depth: int = 2
    max_tickets: int = 25
    follow_text_refs: bool = False
    max_text_chars: int = 6000


@dataclass
class CacheCfg:
    """SQLite cache location."""
    path: str = "~/.cache/rmsum/cache.db"


@dataclass
class OutputCfg:
    """Default directory for generated reports."""
    dir: str = "./reports"


@dataclass
class LoggingCfg:
    """Logging level and rotating log file (empty file = console only)."""
    level: str = "INFO"
    file: str = "rmsum.log"


@dataclass
class Config:
    """Complete application configuration."""
    redmine: RedmineCfg = field(default_factory=RedmineCfg)
    git: GitCfg = field(default_factory=GitCfg)
    llm: LlmCfg = field(default_factory=LlmCfg)
    translate: TranslateCfg = field(default_factory=TranslateCfg)
    analysis: AnalysisCfg = field(default_factory=AnalysisCfg)
    cache: CacheCfg = field(default_factory=CacheCfg)
    output: OutputCfg = field(default_factory=OutputCfg)
    logging: LoggingCfg = field(default_factory=LoggingCfg)


def _build(cls, data, name: str):
    """Instantiate one config section, rejecting unknown keys (typo protection)."""
    if not isinstance(data, dict):
        raise ConfigError(f"'{name}' must be a mapping")
    unknown = set(data) - {f.name for f in fields(cls)}
    if unknown:
        raise ConfigError(f"unknown key(s) in '{name}': {', '.join(sorted(unknown))}")
    return cls(**{k: os.path.expandvars(v) if isinstance(v, str) else v for k, v in data.items()})


def load_config(path: str | Path) -> Config:
    """Load and validate a YAML configuration file.

    String values may reference environment variables as ``${NAME}``.

    Raises:
        ConfigError: file missing, invalid YAML, unknown keys, or required values unset.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise ConfigError(f"config file not found: {p} (copy config.example.yml to start)")
    try:
        raw = yaml.safe_load(p.read_text("utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{p}: top level must be a mapping")
    unknown = set(raw) - {f.name for f in fields(Config)}
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(unknown))}")
    cfg = Config(**{f.name: _build(f.default_factory, raw.get(f.name) or {}, f.name)
                    for f in fields(Config)})
    r = cfg.redmine
    r.url = r.url.rstrip("/")
    cfg.git.base_url = cfg.git.base_url.rstrip("/")
    if not r.url or not r.api_key:
        raise ConfigError("redmine.url and redmine.api_key are required")
    if "${" in r.url + r.api_key:
        raise ConfigError("redmine.url / redmine.api_key reference an unset environment variable")
    return cfg
