"""Application configuration (YAML), kept separate from source code."""
from __future__ import annotations

import copy
import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.geometry import POSITIONS

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

log = logging.getLogger(__name__)
MONITOR_MODES = ("cursor", "primary")


@dataclass
class ApplicationSettings:
    character_position: str = "bottom_right"
    default_character: str = "default_character"
    monitor: str = "cursor"              # which screen shows the character
    start_with_windows: bool = False
    sound_enabled: bool = True


@dataclass
class AnimationSettings:
    enter_duration: float = 1.5          # seconds
    exit_duration: float = 1.5
    reaction_duration: float = 1.8       # happy / angry animation length


@dataclass
class ReminderSettings:
    default_snooze_minutes: int = 10
    missed_grace_minutes: int = 30       # overdue longer than this => "missed", not shown
    auto_snooze_after_seconds: int = 0   # 0 = wait for the user indefinitely


_SECTIONS = {"application": ApplicationSettings, "animation": AnimationSettings,
             "reminder": ReminderSettings}


def _apply(section: Any, data: Any) -> None:
    if not isinstance(data, dict):
        return
    for f in dataclasses.fields(section):
        if f.name not in data:
            continue
        default, value = getattr(section, f.name), data[f.name]
        try:
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    raise ValueError("expected true/false")
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            log.warning("Ignoring invalid config value %s=%r", f.name, value)
            continue
        setattr(section, f.name, value)


@dataclass
class Config:
    application: ApplicationSettings = field(default_factory=ApplicationSettings)
    animation: AnimationSettings = field(default_factory=AnimationSettings)
    reminder: ReminderSettings = field(default_factory=ReminderSettings)

    def validate(self) -> None:
        a, n, r = self.application, self.animation, self.reminder
        if a.character_position not in POSITIONS:
            a.character_position = "bottom_right"
        if a.monitor not in MONITOR_MODES:
            a.monitor = "cursor"
        n.enter_duration = min(max(n.enter_duration, 0.2), 20.0)
        n.exit_duration = min(max(n.exit_duration, 0.2), 20.0)
        n.reaction_duration = min(max(n.reaction_duration, 0.2), 20.0)
        r.default_snooze_minutes = min(max(r.default_snooze_minutes, 1), 1440)
        r.missed_grace_minutes = min(max(r.missed_grace_minutes, 0), 1440)
        r.auto_snooze_after_seconds = min(max(r.auto_snooze_after_seconds, 0), 3600)

    def to_dict(self) -> Dict[str, Any]:
        return {name: dataclasses.asdict(getattr(self, name)) for name in _SECTIONS}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Config":
        cfg = cls()
        if isinstance(data, dict):
            for name in _SECTIONS:
                _apply(getattr(cfg, name), data.get(name))
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Never raises: a missing/corrupt file yields defaults."""
        path = Path(path)
        if yaml is None:
            log.warning("PyYAML is not installed; using default configuration")
            return cls()
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        try:
            with open(str(path), "r", encoding="utf-8") as fh:
                return cls.from_dict(yaml.safe_load(fh))
        except Exception:
            log.exception("Could not read %s; using defaults", path)
            return cls()

    def save(self, path: Path) -> bool:
        if yaml is None:
            log.warning("PyYAML is not installed; settings were not saved")
            return False
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            with open(str(tmp), "w", encoding="utf-8") as fh:
                yaml.safe_dump(copy.deepcopy(self.to_dict()), fh, sort_keys=False)
            tmp.replace(path)
            return True
        except Exception:
            log.exception("Could not save configuration")
            return False
