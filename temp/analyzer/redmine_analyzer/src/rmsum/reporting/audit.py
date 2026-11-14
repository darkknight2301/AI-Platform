"""Excel audit log: one row per ticket per run, appended after each ticket so a crash loses nothing."""

import getpass
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook

from .xlsx import add_sheet

log = logging.getLogger(__name__)

SHEET = "Audit Log"
HEADERS = [
    "Timestamp",
    "User",
    "Ticket",
    "Subject",
    "Outcome",
    "Tickets analysed",
    "Not analysed",
    "Mode",
    "Model",
    "LLM calls",
    "Prompt tokens",
    "Output tokens",
    "Warnings",
    "Rejected statements",
    "Fetch (s)",
    "Translate (s)",
    "LLM (s)",
    "Total (s)",
    "Ollama host",
    "Files",
    "Error",
]
WIDTHS = [20, 14, 9, 40, 11, 10, 10, 11, 16, 9, 10, 10, 9, 10, 9, 10, 9, 9, 18, 50, 60]


@dataclass(frozen=True)
class AuditEntry:
    """What is recorded about one ticket in one run. Never contains credentials or ticket text beyond the subject."""

    ticket_id: int
    outcome: str  # ANALYSED, REUSED or FAILED
    subject: str = ""
    tickets_analysed: int = 0
    not_analysed: int = 0
    mode: str = ""
    model: str = ""
    llm_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    warnings: int = 0
    rejected: int = 0
    fetch_seconds: float = 0.0
    translate_seconds: float = 0.0
    llm_seconds: float = 0.0
    total_seconds: float = 0.0
    ollama_host: str = ""
    files: str = ""
    error: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class AuditLog:
    """Appends entries to an Excel workbook. An empty path disables the log."""

    def __init__(self, path: Optional[Path], user: Optional[str] = None) -> None:
        self._path = path
        self._user = user or _current_user()

    def record(self, entry: AuditEntry) -> Optional[Path]:
        """Append ``entry``. Never raises: an audit problem must not abort the analysis (it is logged instead).

        Returns the file written, or None when disabled or when writing failed.
        """
        if self._path is None:
            return None
        row = [
            entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            self._user,
            f"#{entry.ticket_id}",
            entry.subject,
            entry.outcome,
            entry.tickets_analysed,
            entry.not_analysed,
            entry.mode,
            entry.model,
            entry.llm_calls,
            entry.prompt_tokens,
            entry.output_tokens,
            entry.warnings,
            entry.rejected,
            round(entry.fetch_seconds, 1),
            round(entry.translate_seconds, 1),
            round(entry.llm_seconds, 1),
            round(entry.total_seconds, 1),
            entry.ollama_host,
            entry.files,
            entry.error,
        ]
        try:
            return self._append(row)
        except OSError as exc:
            log.error("could not write audit log %s: %s", self._path, exc)
            return None

    def _append(self, row: list) -> Path:
        existing = self._load_rows()
        wb = Workbook()
        wb.remove(wb.active)
        add_sheet(wb, SHEET, HEADERS, existing + [row], WIDTHS)
        target = self._path
        try:
            _save_atomically(wb, target)
        except PermissionError:
            # Typically the file is open in Excel on Windows. Keep the entry in a side file instead of losing it.
            target = target.with_name(f"{target.stem}.{datetime.now():%Y%m%d-%H%M%S}{target.suffix}")
            log.warning("audit log is locked; writing to %s instead", target)
            _save_atomically(wb, target)
        return target

    def _load_rows(self) -> list[list]:
        """Existing data rows; a corrupt file is set aside rather than overwritten."""
        if not self._path.exists():
            return []
        try:
            wb = load_workbook(self._path, read_only=True)
            try:
                return [list(row) for row in wb[SHEET].iter_rows(min_row=2, values_only=True)]
            finally:
                wb.close()
        except Exception as exc:  # openpyxl raises many unrelated types for damaged files
            backup = self._path.with_suffix(f".corrupt{self._path.suffix}")
            log.error("audit log %s is unreadable (%s); moved to %s and starting a new one", self._path, exc, backup)
            os.replace(self._path, backup)
            return []


def _save_atomically(wb: Workbook, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.stem}.partial{target.suffix}")
    try:
        wb.save(temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no passwd entry in some containers
        return "unknown"
