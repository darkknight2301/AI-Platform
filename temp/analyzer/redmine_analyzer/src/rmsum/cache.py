"""SQLite cache for analyses (invalidated by a fingerprint) and translations."""

import json
import sqlite3
from pathlib import Path

from .models import Analysis


class Cache:
    """Persistent cache. An analysis is valid only while its fingerprint matches."""

    def __init__(self, path: str | Path):
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(p)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS analysis (root_id INTEGER PRIMARY KEY, "
            "fingerprint TEXT NOT NULL, data TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS translation (hash TEXT PRIMARY KEY, text TEXT NOT NULL);")

    def get_analysis(self, root_id: int, fingerprint: str) -> Analysis | None:
        """Return the cached analysis only if it was made from the same ticket state."""
        row = self._db.execute("SELECT data FROM analysis WHERE root_id=? AND fingerprint=?",
                               (root_id, fingerprint)).fetchone()
        return Analysis.from_dict(json.loads(row[0])) if row else None

    def put_analysis(self, a: Analysis) -> None:
        """Store (or replace) the analysis of ``a.root_id``."""
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO analysis VALUES (?,?,?)",
                             (a.root_id, a.meta["fingerprint"], json.dumps(a.to_dict(), ensure_ascii=False)))

    def get_translation(self, key: str) -> str | None:
        """Cached translation for a text hash, if any."""
        row = self._db.execute("SELECT text FROM translation WHERE hash=?", (key,)).fetchone()
        return row[0] if row else None

    def put_translation(self, key: str, text: str) -> None:
        """Store a translation under its text hash."""
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO translation VALUES (?,?)", (key, text))
