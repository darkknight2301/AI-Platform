"""Writes report files atomically, so a crash or full disk never leaves a half-written report behind."""

import json
import os
from collections.abc import Callable, Collection
from pathlib import Path

from ..domain.models import Analysis
from .html import render_html
from .xlsx import write_xlsx

FORMATS = ("html", "xlsx", "json")


def report_path(directory: Path, root_id: int, fmt: str) -> Path:
    """Canonical report filename: ``redmine_<id>.<format>``."""
    return directory / f"redmine_{root_id}.{fmt}"


def atomic_write(path: Path, write: Callable[[Path], None]) -> None:
    """Call ``write(temp_path)`` then rename over ``path``; the temp file is removed on failure."""
    temp = path.with_name(f".{path.stem}.partial{path.suffix}")
    try:
        write(temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_reports(a: Analysis, directory: Path, formats: Collection[str]) -> list[Path]:
    """Write the requested formats. JSON is always written: it is the stored state used to skip unchanged tickets."""
    directory.mkdir(parents=True, exist_ok=True)
    writers: dict[str, Callable[[Path], None]] = {
        "html": lambda p: p.write_text(render_html(a), "utf-8"),
        "xlsx": lambda p: write_xlsx(a, p),
        "json": lambda p: p.write_text(json.dumps(a.to_dict(), ensure_ascii=False, indent=2), "utf-8"),
    }
    written = []
    for fmt in FORMATS:
        if fmt == "json" or fmt in formats:
            path = report_path(directory, a.root_id, fmt)
            atomic_write(path, writers[fmt])
            written.append(path)
    return written


def load_previous(path: Path) -> Analysis | None:
    """Load a previously written JSON analysis; None if absent, unreadable or from an incompatible version."""
    try:
        return Analysis.from_dict(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None
