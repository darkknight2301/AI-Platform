"""Logging configuration with secret redaction."""

import logging
import logging.handlers
from pathlib import Path

from .config import LoggingCfg

LOGGER_NAME = "rmsum"


class SecretRedactor(logging.Filter):
    """Replaces registered secrets in log messages, so a stray log line can never leak a credential."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()

    def register(self, secret: str) -> None:
        """Start redacting ``secret`` (ignored when too short to be meaningful)."""
        if len(secret) >= 4:
            self._secrets.add(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self._secrets:
            message = message.replace(secret, "***")
        record.msg, record.args = message, None
        return True


def configure_logging(cfg: LoggingCfg, verbose: bool = False) -> SecretRedactor:
    """Attach console and (optional) rotating-file handlers to the ``rmsum`` logger only.

    The root logger is left untouched so embedding or testing does not disturb global logging state.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    redactor = SecretRedactor()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if cfg.file:
        path = Path(cfg.file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else cfg.level.upper())
    logger.propagate = False
    return redactor
