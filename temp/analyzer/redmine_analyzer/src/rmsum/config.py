"""YAML configuration: loading, ``${ENV_VAR}`` expansion, type coercion and range validation.

All sections are frozen dataclasses: after loading, configuration cannot change behind the
application's back. Command-line overrides use :func:`dataclasses.replace`.
"""

import logging
import os
from dataclasses import MISSING, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from .errors import ConfigError


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


@dataclass(frozen=True)
class RedmineCfg:
    """Redmine REST API access."""

    url: str = ""
    api_key: str = field(default="", repr=False)  # repr=False keeps it out of tracebacks and logs
    timeout: float = 30.0
    verify_ssl: bool = True
    page_size: int = 100
    retries: int = 3

    def __post_init__(self) -> None:
        _check(self.timeout > 0, "redmine.timeout must be > 0")
        _check(1 <= self.page_size <= 100, "redmine.page_size must be between 1 and 100 (Redmine's maximum)")
        _check(self.retries >= 1, "redmine.retries must be >= 1")


@dataclass(frozen=True)
class GitCfg:
    """GitLab project URL used to turn bare ``!123`` / commit / branch references into links."""

    base_url: str = ""


@dataclass(frozen=True)
class LlmCfg:
    """Local LLM endpoint and deterministic generation settings."""

    backend: str = "ollama"
    endpoint: str = "http://localhost:11434"
    model: str = "qwen3:27b"
    num_ctx: int = 16384
    max_output_tokens: int = 3000
    seed: int = 42
    timeout: float = 900.0
    think: Optional[bool] = None  # None = do not send the option
    keep_alive: str = "30m"  # keeps the 27B model loaded between tickets
    retries: int = 2

    def __post_init__(self) -> None:
        _check(self.backend != "", "llm.backend must not be empty")
        _check(self.num_ctx >= 2048, "llm.num_ctx must be >= 2048")
        _check(64 <= self.max_output_tokens < self.num_ctx // 2, "llm.max_output_tokens must be >= 64 and < num_ctx/2")
        _check(self.timeout > 0, "llm.timeout must be > 0")
        _check(self.retries >= 1, "llm.retries must be >= 1")


@dataclass(frozen=True)
class SshCfg:
    """Optional SSH access to a remote Ollama.

    Only non-secret defaults live here. Host, username and password are asked for at run time
    (see :mod:`rmsum.adapters.ssh`), so no password is ever stored in a configuration file.
    """

    enabled: bool = False
    host: str = ""  # default offered at the prompt
    port: int = 22
    username: str = ""  # default offered at the prompt
    key_file: str = ""  # optional private key; the runtime password then unlocks the key if needed
    remote_host: str = "127.0.0.1"  # where Ollama listens, as seen from the SSH server
    remote_port: int = 11434
    trust_unknown_host: bool = False  # True disables host-key protection against man-in-the-middle

    def __post_init__(self) -> None:
        _check(1 <= self.port <= 65535, "ssh.port must be between 1 and 65535")
        _check(1 <= self.remote_port <= 65535, "ssh.remote_port must be between 1 and 65535")


@dataclass(frozen=True)
class TranslateCfg:
    """Translation through ``<module>.translate(text) -> str``, called once per batch of texts."""

    enabled: bool = True
    module: str = "api"
    include_original: bool = True
    batch_chars: int = 4000  # upper bound of characters per translate call
    batch_items: int = 20  # upper bound of texts per translate call

    def __post_init__(self) -> None:
        _check(self.batch_chars >= 200, "translate.batch_chars must be >= 200")
        _check(self.batch_items >= 1, "translate.batch_items must be >= 1")


@dataclass(frozen=True)
class AnalysisCfg:
    """Ticket graph traversal and context limits."""

    max_depth: int = 2
    max_tickets: int = 25
    follow_text_refs: bool = False
    max_text_chars: int = 6000

    def __post_init__(self) -> None:
        _check(self.max_depth >= 0, "analysis.max_depth must be >= 0")
        _check(self.max_tickets >= 1, "analysis.max_tickets must be >= 1")
        _check(self.max_text_chars >= 200, "analysis.max_text_chars must be >= 200")


@dataclass(frozen=True)
class OutputCfg:
    """Report directory and the Excel audit log (empty ``audit_file`` disables the audit log)."""

    dir: str = "./reports"
    audit_file: str = "audit_log.xlsx"


@dataclass(frozen=True)
class LoggingCfg:
    """Logging level and rotating log file (empty file = console only)."""

    level: str = "INFO"
    file: str = "rmsum.log"

    def __post_init__(self) -> None:
        # getLevelName returns an int for known level names and a "Level X" string otherwise
        _check(isinstance(logging.getLevelName(self.level.upper()), int), f"logging.level '{self.level}' is not valid")


@dataclass(frozen=True)
class Config:
    """Complete application configuration."""

    redmine: RedmineCfg = field(default_factory=RedmineCfg)
    git: GitCfg = field(default_factory=GitCfg)
    llm: LlmCfg = field(default_factory=LlmCfg)
    ssh: SshCfg = field(default_factory=SshCfg)
    translate: TranslateCfg = field(default_factory=TranslateCfg)
    analysis: AnalysisCfg = field(default_factory=AnalysisCfg)
    output: OutputCfg = field(default_factory=OutputCfg)
    logging: LoggingCfg = field(default_factory=LoggingCfg)


# Keys that existed in earlier versions; a precise message beats "unknown key".
_REMOVED = {
    ("", "cache"): "the 'cache' section was removed: rmsum no longer uses a database",
    ("ssh", "password"): "ssh.password is not supported: the SSH password is asked for at run time",
}


def _coerce(where: str, value: Any, default: Any) -> Any:
    """Convert a YAML value to the type of the field's default, rejecting mismatches."""
    kind = type(default)
    if default is None:  # the only Optional field is llm.think
        if value is None or isinstance(value, bool):
            return value
        raise ConfigError(f"{where} must be true, false or null, got {value!r}")
    plain_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is bool and isinstance(value, bool):
        return value
    if kind is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if kind is float and plain_number:
        return float(value)
    if kind is str and (isinstance(value, str) or plain_number):
        return str(value)
    raise ConfigError(f"{where} must be of type {kind.__name__}, got {value!r}")


def _build_section(cls: type, data: Any, section: str) -> Any:
    """Instantiate one config section, rejecting unknown keys (typo protection)."""
    _check(isinstance(data, dict), f"'{section}' must be a mapping")
    known = {f.name: f for f in fields(cls)}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if _REMOVED.get((section, key)):
            raise ConfigError(_REMOVED[(section, key)])
        _check(key in known, f"unknown key '{key}' in '{section}'")
        default = known[key].default
        _check(default is not MISSING, f"internal error: '{section}.{key}' has no default")
        if isinstance(value, str):
            value = os.path.expandvars(value)
        kwargs[key] = _coerce(f"{section}.{key}", value, default)
    return cls(**kwargs)


def load_config(path: Union[str, Path]) -> Config:
    """Load and validate a YAML configuration file.

    String values may reference environment variables as ``${NAME}``.

    Raises:
        ConfigError: file missing, invalid YAML, unknown keys, out-of-range values or required values unset.
    """
    p = Path(path).expanduser()
    _check(p.is_file(), f"config file not found: {p} (copy config.example.yml to start)")
    try:
        raw = yaml.safe_load(p.read_text("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc
    _check(isinstance(raw, dict), f"{p}: top level must be a mapping")
    for name in raw:
        if _REMOVED.get(("", name)):
            raise ConfigError(_REMOVED[("", name)])
    sections = {f.name: f for f in fields(Config)}
    unknown = set(raw) - set(sections)
    _check(not unknown, f"unknown section(s): {', '.join(sorted(unknown))}")
    built = {
        name: _build_section(f.default_factory, raw.get(name) or {}, name)  # type: ignore[arg-type]
        for name, f in sections.items()
    }
    cfg = Config(**built)

    redmine = cfg.redmine
    _check(redmine.url and redmine.api_key, "redmine.url and redmine.api_key are required")
    _check("${" not in redmine.url + redmine.api_key, "redmine.url / redmine.api_key reference an unset variable")
    return _normalise(cfg)


def _normalise(cfg: Config) -> Config:
    """Canonical forms: no trailing slashes, expanded key path."""
    ssh = cfg.ssh
    if ssh.key_file:
        ssh = replace(ssh, key_file=str(Path(ssh.key_file).expanduser()))
    return replace(
        cfg,
        redmine=replace(cfg.redmine, url=cfg.redmine.url.rstrip("/")),
        git=replace(cfg.git, base_url=cfg.git.base_url.rstrip("/")),
        ssh=ssh,
    )
