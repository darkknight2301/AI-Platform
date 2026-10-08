"""Logging configuration: rotating file + console (console skipped under pythonw)."""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(logs_dir: Path, level: str = "") -> None:
    level_name = (level or os.environ.get("DESKTOP_REMINDER_LOG", "INFO")).upper()
    root = logging.getLogger()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    for h in list(root.handlers):  # idempotent
        root.removeHandler(h)
    formatter = logging.Formatter(_FORMAT)
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            str(logs_dir / "desktop_reminder.log"), maxBytes=512 * 1024,
            backupCount=3, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:  # pythonw.exe has no stderr
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formatter)
        root.addHandler(sh)
