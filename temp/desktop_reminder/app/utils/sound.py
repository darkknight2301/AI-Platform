"""Sound effects, deliberately independent from any character implementation."""
import logging
from pathlib import Path
from typing import Iterable, Optional, Set

try:  # Windows only
    import winsound  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    winsound = None

log = logging.getLogger(__name__)

EVENTS = ("enter", "happy", "angry", "reminder", "exit")


class SoundPlayer:
    """Plays ``<event>.wav``; a character folder may override via ``sounds/``."""

    def __init__(self, default_dir: Path):
        self._default_dir = Path(default_dir)
        self._warned: Set[str] = set()

    def find(self, event: str, extra_dirs: Iterable[Path] = ()) -> Optional[Path]:
        for d in list(extra_dirs) + [self._default_dir]:
            p = Path(d) / (event + ".wav")
            if p.is_file():
                return p
        return None

    def play(self, event: str, extra_dirs: Iterable[Path] = ()) -> bool:
        path = self.find(event, extra_dirs)
        if path is None:
            if event not in self._warned:
                self._warned.add(event)
                log.warning("Sound file '%s.wav' not found; skipping", event)
            return False
        if winsound is None:
            log.debug("winsound unavailable; not playing %s", path)
            return False
        try:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC
                               | winsound.SND_NODEFAULT)
            return True
        except Exception:
            log.warning("Could not play %s", path, exc_info=True)
            return False
