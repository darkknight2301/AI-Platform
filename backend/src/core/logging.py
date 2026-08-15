"""
Structured logging configuration.

Uses the standard library `logging` module with a JSON formatter so logs
are easy to ingest in production. Never logs secrets, API keys, or
authentication tokens — call sites are responsible for keeping sensitive
values out of log records.
"""
from __future__ import annotations

import json
import logging
import sys
from collections import deque
from datetime import UTC, datetime
from typing import Any

from src.core.config import get_settings

_RESERVED_ATTRS = set(logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys())

# Bounded in-memory ring buffer of recent structured log entries,
# surfaced to Developer/Owner roles via GET /api/v1/system/logs. Not a
# durable log store — a real deployment should ship logs to an
# external aggregator; this exists so the diagnostics endpoint has
# something real to show without standing up that infrastructure here.
_RECENT_LOGS_MAXLEN = 500
recent_log_entries: deque[dict[str, Any]] = deque(maxlen=_RECENT_LOGS_MAXLEN)


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        recent_log_entries.append(
            {
                "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Include any extra fields passed via `logger.info(..., extra={...})`
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    # Avoid duplicate handlers on reload (e.g. under uvicorn --reload)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.addHandler(RingBufferHandler())

    # Quiet noisy third-party loggers unless debug is on.
    if not settings.debug:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
