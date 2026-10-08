"""Reminder data model: plain data + validation, no scheduling and no GUI."""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.reminders.errors import InvalidReminderError
from app.utils.timefmt import normalize_hhmm

REPEAT_ONCE = "once"
REPEAT_DAILY = "daily"
REPEAT_WEEKLY = "weekly"
REPEAT_INTERVAL = "interval"
REPEAT_MODES = (REPEAT_ONCE, REPEAT_DAILY, REPEAT_WEEKLY, REPEAT_INTERVAL)

# Status = last known outcome / state of the reminder.
STATUS_SCHEDULED = "scheduled"
STATUS_ACTIVE = "active"        # currently being shown by a character
STATUS_SNOOZED = "snoozed"
STATUS_COMPLETED = "completed"
STATUS_MISSED = "missed"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_SCHEDULED, STATUS_ACTIVE, STATUS_SNOOZED, STATUS_COMPLETED,
            STATUS_MISSED, STATUS_DISABLED)

OUTCOME_FIRED = "fired"
OUTCOME_COMPLETED = "completed"
OUTCOME_SNOOZED = "snoozed"
OUTCOME_MISSED = "missed"

MAX_MESSAGE_LEN = 200


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


@dataclass
class Reminder:
    message: str
    time: str                                   # "HH:MM" 24h, local time
    repeat: str = REPEAT_DAILY
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    date: Optional[str] = None                  # "YYYY-MM-DD", used by one-time reminders
    weekdays: List[int] = field(default_factory=list)   # 0=Mon .. 6=Sun (weekly)
    interval_minutes: int = 60                  # interval repeat: first fire at `time`
    snooze_minutes: int = 10
    sound_enabled: bool = True
    character: str = ""                         # "" = use the default character
    enabled: bool = True
    status: str = STATUS_SCHEDULED
    next_due: Optional[str] = None              # ISO local datetime, managed by the manager
    last_triggered: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    # ------------------------------------------------------------------ validation
    def validate(self) -> None:
        """Normalises fields in place; raises InvalidReminderError when unusable."""
        if not isinstance(self.message, str) or not self.message.strip():
            raise InvalidReminderError("The reminder message cannot be empty.")
        self.message = self.message.strip()
        if len(self.message) > MAX_MESSAGE_LEN:
            raise InvalidReminderError(
                "The reminder message is too long (max %d characters)." % MAX_MESSAGE_LEN)
        try:
            self.time = normalize_hhmm(self.time)
        except ValueError as exc:
            raise InvalidReminderError("Invalid time: %s" % exc)
        if self.repeat not in REPEAT_MODES:
            raise InvalidReminderError("Unknown repeat mode %r." % (self.repeat,))
        if self.date:
            try:
                date.fromisoformat(self.date)
            except (TypeError, ValueError):
                raise InvalidReminderError("Invalid date %r (expected YYYY-MM-DD)." % (self.date,))
        else:
            self.date = None
        if not isinstance(self.weekdays, list) or any(
                not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6
                for d in self.weekdays):
            raise InvalidReminderError("Weekdays must be numbers 0 (Mon) to 6 (Sun).")
        self.weekdays = sorted(set(self.weekdays))
        if self.repeat == REPEAT_WEEKLY and not self.weekdays:
            raise InvalidReminderError("Choose at least one weekday for a weekly reminder.")
        if not isinstance(self.interval_minutes, int) or not 1 <= self.interval_minutes <= 10080:
            raise InvalidReminderError("The interval must be between 1 minute and 7 days.")
        if not isinstance(self.snooze_minutes, int) or not 1 <= self.snooze_minutes <= 1440:
            raise InvalidReminderError("The snooze time must be between 1 minute and 24 hours.")
        if not isinstance(self.character, str):
            raise InvalidReminderError("Invalid character id.")

    # ------------------------------------------------------------------ helpers
    def due_datetime(self) -> Optional[datetime]:
        if not self.next_due:
            return None
        try:
            return datetime.fromisoformat(self.next_due)
        except ValueError:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "Reminder":
        """Build from untrusted JSON; raises InvalidReminderError on bad data."""
        if not isinstance(data, dict):
            raise InvalidReminderError("Reminder entry is not an object.")
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        if "message" not in kwargs or "time" not in kwargs:
            raise InvalidReminderError("Reminder entry needs 'message' and 'time'.")
        try:
            for key in ("interval_minutes", "snooze_minutes"):
                if key in kwargs:
                    kwargs[key] = int(kwargs[key])
            if "weekdays" in kwargs:
                kwargs["weekdays"] = [int(d) for d in kwargs["weekdays"]]
            for key in ("sound_enabled", "enabled"):
                if key in kwargs:
                    kwargs[key] = bool(kwargs[key])
            if "id" in kwargs:
                kwargs["id"] = str(kwargs["id"])
            reminder = cls(**kwargs)
        except (TypeError, ValueError) as exc:
            raise InvalidReminderError("Malformed reminder entry: %s" % exc)
        reminder.validate()
        if reminder.status not in STATUSES:
            reminder.status = STATUS_SCHEDULED
        if reminder.next_due and reminder.due_datetime() is None:
            reminder.next_due = None   # recomputed by the manager
        return reminder


@dataclass
class HistoryEntry:
    timestamp: str
    reminder_id: str
    message: str
    outcome: str
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "HistoryEntry":
        if not isinstance(data, dict):
            raise ValueError("history entry is not an object")
        return cls(timestamp=str(data["timestamp"]), reminder_id=str(data["reminder_id"]),
                   message=str(data.get("message", "")), outcome=str(data["outcome"]),
                   detail=str(data.get("detail", "")))
