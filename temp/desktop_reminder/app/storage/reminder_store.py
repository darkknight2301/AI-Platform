"""Persistence layer. The engine only depends on the abstract classes, so a
SQLite implementation can be dropped in later without touching it."""
from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from app.reminders.reminder import HistoryEntry, Reminder

log = logging.getLogger(__name__)


class ReminderStore(ABC):
    @abstractmethod
    def load(self) -> List[Reminder]: ...

    @abstractmethod
    def save(self, reminders: List[Reminder]) -> None: ...


class HistoryStore(ABC):
    @abstractmethod
    def load(self) -> List[HistoryEntry]: ...

    @abstractmethod
    def append(self, entry: HistoryEntry) -> None: ...


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(str(tmp), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))


def _read_json(path: Path) -> Optional[Any]:
    """Returns parsed JSON, or None if missing. A corrupt file is moved aside."""
    if not path.exists():
        return None
    try:
        with open(str(path), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        backup = path.with_name("%s.corrupt-%s" % (path.name, datetime.now().strftime("%Y%m%d-%H%M%S")))
        log.error("Could not read %s; moving it to %s and starting fresh", path, backup,
                  exc_info=True)
        try:
            os.replace(str(path), str(backup))
        except OSError:
            log.exception("Could not back up corrupt file %s", path)
        return None


class JsonReminderStore(ReminderStore):
    VERSION = 1

    def __init__(self, path: Path):
        self._path = Path(path)

    def load(self) -> List[Reminder]:
        data = _read_json(self._path)
        if data is None:
            return []
        items = data.get("reminders") if isinstance(data, dict) else data
        if not isinstance(items, list):
            log.error("%s has an unexpected structure; ignoring it", self._path)
            return []
        result, seen = [], set()
        for index, raw in enumerate(items):
            try:
                reminder = Reminder.from_dict(raw)
            except Exception as exc:     # one bad entry must not lose the others
                log.warning("Skipping invalid reminder #%d in %s: %s", index, self._path, exc)
                continue
            if reminder.id in seen:
                log.warning("Skipping reminder #%d with duplicate id %s", index, reminder.id)
                continue
            seen.add(reminder.id)
            result.append(reminder)
        return result

    def save(self, reminders: List[Reminder]) -> None:
        _atomic_write_json(self._path, {"version": self.VERSION,
                                        "reminders": [r.to_dict() for r in reminders]})


class JsonHistoryStore(HistoryStore):
    def __init__(self, path: Path, max_entries: int = 500):
        self._path = Path(path)
        self._max = max_entries
        self._lock = threading.Lock()
        self._entries: Optional[List[HistoryEntry]] = None

    def _ensure_loaded(self) -> List[HistoryEntry]:
        if self._entries is None:
            data = _read_json(self._path)
            items = data.get("history", []) if isinstance(data, dict) else []
            entries = []
            for raw in items if isinstance(items, list) else []:
                try:
                    entries.append(HistoryEntry.from_dict(raw))
                except Exception:
                    log.warning("Skipping invalid history entry")
            self._entries = entries
        return self._entries

    def load(self) -> List[HistoryEntry]:
        with self._lock:
            return list(self._ensure_loaded())

    def append(self, entry: HistoryEntry) -> None:
        with self._lock:
            entries = self._ensure_loaded()
            entries.append(entry)
            del entries[:-self._max]
            _atomic_write_json(self._path, {"version": 1,
                                            "history": [e.to_dict() for e in entries]})
