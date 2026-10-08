"""Filesystem layout. Everything is relative to one root so the app is portable."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def reminders_file(self) -> Path:
        return self.data_dir / "reminders.json"

    @property
    def history_file(self) -> Path:
        return self.data_dir / "history.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def sounds_dir(self) -> Path:
        return self.assets_dir / "sounds"

    @property
    def user_characters_dir(self) -> Path:
        return self.assets_dir / "characters"

    @property
    def builtin_characters_dir(self) -> Path:
        return self.root / "app" / "characters" / "builtin"

    def ensure(self) -> None:
        for d in (self.config_dir, self.data_dir, self.logs_dir, self.sounds_dir,
                  self.user_characters_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_paths() -> AppPaths:
    """Project root, or $DESKTOP_REMINDER_HOME when set (handy for tests)."""
    env = os.environ.get("DESKTOP_REMINDER_HOME")
    root = Path(env) if env else Path(__file__).resolve().parents[2]
    return AppPaths(root=root)
