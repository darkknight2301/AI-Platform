"""Scheduling rules (pure functions) and the background polling Scheduler.

Everything here is GUI-free. The Scheduler thread only *claims* due reminders
from the manager and hands them to a callback; the GUI layer is responsible for
marshalling that callback onto the UI thread.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Callable, List, Optional

from app.reminders.reminder import (REPEAT_DAILY, REPEAT_INTERVAL, REPEAT_ONCE,
                                    REPEAT_WEEKLY, Reminder)
from app.utils.timefmt import parse_hhmm

log = logging.getLogger(__name__)


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def next_occurrence(reminder: Reminder, after: datetime) -> Optional[datetime]:
    """First occurrence strictly after ``after``; None if there is none (past one-shot)."""
    hour, minute = parse_hhmm(reminder.time)
    if reminder.repeat == REPEAT_ONCE and reminder.date:
        candidate = _at(date.fromisoformat(reminder.date), hour, minute)
        return candidate if candidate > after else None
    if reminder.repeat == REPEAT_WEEKLY:
        for offset in range(8):
            day = after.date() + timedelta(days=offset)
            if day.weekday() in reminder.weekdays:
                candidate = _at(day, hour, minute)
                if candidate > after:
                    return candidate
        return None
    # once (no date yet), daily and interval: next wall-clock hit of HH:MM
    candidate = _at(after.date(), hour, minute)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def advance_after_fire(reminder: Reminder, now: datetime) -> Optional[datetime]:
    """Next due time once a firing has been handled (completed/missed)."""
    if reminder.repeat == REPEAT_ONCE:
        return None
    if reminder.repeat == REPEAT_INTERVAL:
        step = timedelta(minutes=reminder.interval_minutes)
        base = reminder.due_datetime() or now
        k = max(1, (now - base) // step + 1) if now >= base else 1
        return base + step * k
    return next_occurrence(reminder, now)


def snooze_until(now: datetime, minutes: int) -> datetime:
    return now.replace(microsecond=0) + timedelta(minutes=minutes)


class Scheduler:
    """Polls the manager once per second on a daemon thread."""

    def __init__(self, manager, on_due: Callable[[List[Reminder]], None],
                 poll_interval: float = 1.0, clock: Callable[[], datetime] = datetime.now):
        self._manager = manager
        self._on_due = on_due
        self._interval = poll_interval
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def poll(self, now: Optional[datetime] = None) -> List[Reminder]:
        """One scheduling pass. Never raises, so one bad reminder cannot kill the loop."""
        now = now or self._clock()
        try:
            due = self._manager.claim_due(now)
        except Exception:
            log.exception("Scheduler pass failed")
            return []
        if due:
            try:
                self._on_due(due)
            except Exception:
                log.exception("Delivering due reminders failed; releasing them")
                self._manager.release([r.id for r in due])
        return due

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ReminderScheduler", daemon=True)
        self._thread.start()
        log.info("Scheduler started")

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self._thread = None
        log.info("Scheduler stopped")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.poll()
