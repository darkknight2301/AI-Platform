"""ReminderManager: the single owner of reminder state (CRUD + lifecycle).

Thread-safe: the scheduler thread calls ``claim_due`` while the GUI thread edits.
It knows nothing about characters or Qt.
"""
from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Set

from app.reminders.errors import (DuplicateReminderError, InvalidReminderError,
                                  ReminderNotFoundError)
from app.reminders.reminder import (OUTCOME_COMPLETED, OUTCOME_FIRED, OUTCOME_MISSED,
                                    OUTCOME_SNOOZED, REPEAT_ONCE, REPEAT_WEEKLY,
                                    REPEAT_INTERVAL, STATUS_ACTIVE, STATUS_COMPLETED,
                                    STATUS_DISABLED, STATUS_MISSED, STATUS_SCHEDULED,
                                    STATUS_SNOOZED, HistoryEntry, Reminder)
from app.reminders.scheduler import advance_after_fire, next_occurrence, snooze_until
from app.storage.reminder_store import HistoryStore, ReminderStore
from app.utils.timefmt import parse_hhmm

log = logging.getLogger(__name__)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


class ReminderManager:
    def __init__(self, store: ReminderStore, history: Optional[HistoryStore] = None,
                 clock: Callable[[], datetime] = datetime.now,
                 missed_grace: timedelta = timedelta(minutes=30)):
        self._store = store
        self._history = history
        self._clock = clock
        self._grace = missed_grace
        self._lock = threading.RLock()
        self._reminders: List[Reminder] = []
        self._active: Set[str] = set()
        self._paused = False
        self._listeners: List[Callable[[], None]] = []
        self._load()

    # ------------------------------------------------------------------ setup
    def _load(self) -> None:
        try:
            loaded = self._store.load()
        except Exception:
            log.exception("Loading reminders failed; starting with an empty list")
            loaded = []
        now = self._clock()
        for r in loaded:
            if r.status == STATUS_ACTIVE:           # app closed while it was showing
                r.status = STATUS_SCHEDULED
            if not r.enabled:
                r.next_due = None
                if r.status not in (STATUS_COMPLETED, STATUS_MISSED):
                    r.status = STATUS_DISABLED
            elif r.due_datetime() is None:
                self._schedule_fresh(r, now, strict=False)
        self._reminders = loaded
        self._save()

    def set_missed_grace(self, grace: timedelta) -> None:
        with self._lock:
            self._grace = grace

    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    # ------------------------------------------------------------------ queries
    def list(self) -> List[Reminder]:
        with self._lock:
            return [copy.deepcopy(r) for r in self._reminders]

    def get(self, reminder_id: str) -> Optional[Reminder]:
        with self._lock:
            r = self._find(reminder_id)
            return copy.deepcopy(r) if r else None

    def history(self, limit: int = 200) -> List[HistoryEntry]:
        if self._history is None:
            return []
        return list(reversed(self._history.load()))[:limit]

    @property
    def paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------ CRUD
    def add(self, reminder: Reminder) -> Reminder:
        with self._lock:
            new = copy.deepcopy(reminder)
            new.validate()
            if any(r.id == new.id for r in self._reminders):
                new.id = Reminder(message="x", time="00:00").id
            self._check_duplicate(new)
            self._prepare_schedule(new, self._clock())
            self._reminders.append(new)
            self._save()
            result = copy.deepcopy(new)
        self._notify()
        return result

    def update(self, reminder: Reminder) -> Reminder:
        with self._lock:
            old = self._find(reminder.id)
            if old is None:
                raise ReminderNotFoundError("Reminder %s no longer exists." % reminder.id)
            new = copy.deepcopy(reminder)
            new.validate()
            self._check_duplicate(new, ignore_id=new.id)
            new.created_at, new.last_triggered = old.created_at, old.last_triggered
            self._prepare_schedule(new, self._clock())
            self._reminders[self._reminders.index(old)] = new
            self._save()
            result = copy.deepcopy(new)
        self._notify()
        return result

    def delete(self, reminder_id: str) -> None:
        with self._lock:
            r = self._find(reminder_id)
            if r is None:
                raise ReminderNotFoundError("Reminder %s no longer exists." % reminder_id)
            self._reminders.remove(r)
            self._active.discard(reminder_id)
            self._save()
        self._notify()

    def set_enabled(self, reminder_id: str, enabled: bool) -> Reminder:
        with self._lock:
            r = self._find(reminder_id)
            if r is None:
                raise ReminderNotFoundError("Reminder %s no longer exists." % reminder_id)
            now = self._clock()
            if enabled and r.repeat == REPEAT_ONCE and r.date:
                h, m = parse_hhmm(r.time)
                d = datetime.fromisoformat(r.date)
                if d.replace(hour=h, minute=m) <= now:
                    r.date = None            # stale one-shot: re-arm for the next occurrence
            r.enabled = enabled
            self._prepare_schedule(r, now)
            self._save()
            result = copy.deepcopy(r)
        self._notify()
        return result

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
        log.info("Reminders %s", "paused" if paused else "resumed")
        self._notify()

    # ------------------------------------------------------------------ lifecycle
    def reconcile(self, now: Optional[datetime] = None) -> int:
        """Call at start-up: reminders overdue beyond the grace period become 'missed'."""
        now = now or self._clock()
        with self._lock:
            changed = self._expire_missed(now)
            if changed:
                self._save()
        if changed:
            self._notify()
        return changed

    def claim_due(self, now: Optional[datetime] = None) -> List[Reminder]:
        """Atomically mark due reminders as active and return copies to display."""
        now = now or self._clock()
        with self._lock:
            changed = self._expire_missed(now)
            due: List[Reminder] = []
            if not self._paused:
                candidates = [r for r in self._reminders if r.enabled
                              and r.id not in self._active
                              and r.due_datetime() is not None and r.due_datetime() <= now]
                for r in sorted(candidates, key=lambda x: x.due_datetime()):
                    self._active.add(r.id)
                    r.status = STATUS_ACTIVE
                    r.last_triggered = _iso(now)
                    self._record(r, OUTCOME_FIRED)
                    due.append(copy.deepcopy(r))
            if due or changed:
                self._save()
        if due or changed:
            self._notify()
        return due

    def release(self, reminder_ids: List[str]) -> None:
        """Give claimed reminders back (display failed); they will be claimed again."""
        with self._lock:
            for rid in reminder_ids:
                self._active.discard(rid)
                r = self._find(rid)
                if r and r.status == STATUS_ACTIVE:
                    r.status = STATUS_SCHEDULED
            self._save()

    def complete(self, reminder_id: str) -> bool:
        """User pressed Done. False when the id is unknown (e.g. a test reminder)."""
        with self._lock:
            r = self._find(reminder_id)
            if r is None:
                return False
            now = self._clock()
            self._active.discard(reminder_id)
            self._record(r, OUTCOME_COMPLETED)
            nxt = advance_after_fire(r, now)
            r.status = STATUS_COMPLETED
            if nxt is None:
                r.enabled, r.next_due = False, None
            else:
                r.next_due = _iso(nxt)
            self._save()
        self._notify()
        return True

    def snooze(self, reminder_id: str, minutes: Optional[int] = None) -> bool:
        with self._lock:
            r = self._find(reminder_id)
            if r is None:
                return False
            minutes = r.snooze_minutes if minutes is None else minutes
            if not isinstance(minutes, int) or not 1 <= minutes <= 1440:
                raise InvalidReminderError("The snooze time must be between 1 minute and 24 hours.")
            self._active.discard(reminder_id)
            r.status = STATUS_SNOOZED
            r.next_due = _iso(snooze_until(self._clock(), minutes))
            self._record(r, OUTCOME_SNOOZED, "%d min" % minutes)
            self._save()
        self._notify()
        return True

    # ------------------------------------------------------------------ internals
    def _find(self, reminder_id: str) -> Optional[Reminder]:
        for r in self._reminders:
            if r.id == reminder_id:
                return r
        return None

    @staticmethod
    def _dup_key(r: Reminder):
        return (r.message.casefold(), r.time, r.repeat,
                r.date if r.repeat == REPEAT_ONCE else None,
                tuple(r.weekdays) if r.repeat == REPEAT_WEEKLY else (),
                r.interval_minutes if r.repeat == REPEAT_INTERVAL else 0)

    def _check_duplicate(self, new: Reminder, ignore_id: Optional[str] = None) -> None:
        key = self._dup_key(new)
        for r in self._reminders:
            if r.id != ignore_id and self._dup_key(r) == key:
                raise DuplicateReminderError(
                    "A reminder '%s' at %s with the same schedule already exists." % (r.message, r.time))

    def _schedule_fresh(self, r: Reminder, now: datetime, strict: bool) -> None:
        due = next_occurrence(r, now)
        if due is None:
            if strict:
                raise InvalidReminderError("That date and time is already in the past.")
            r.enabled, r.status, r.next_due = False, STATUS_MISSED, None
            return
        if r.repeat == REPEAT_ONCE and not r.date:
            r.date = due.date().isoformat()     # pin a one-shot to a concrete day
        r.next_due = _iso(due)
        r.status = STATUS_SCHEDULED

    def _prepare_schedule(self, r: Reminder, now: datetime) -> None:
        if r.enabled:
            self._schedule_fresh(r, now, strict=True)
        else:
            r.next_due, r.status = None, STATUS_DISABLED

    def _expire_missed(self, now: datetime) -> int:
        count = 0
        for r in self._reminders:
            due = r.due_datetime()
            if not r.enabled or r.id in self._active or due is None or now - due <= self._grace:
                continue
            self._record(r, OUTCOME_MISSED, "due %s" % r.next_due)
            nxt = advance_after_fire(r, now)
            r.status = STATUS_MISSED
            if nxt is None:
                r.enabled, r.next_due = False, None
            else:
                r.next_due = _iso(nxt)
            count += 1
        return count

    def _record(self, r: Reminder, outcome: str, detail: str = "") -> None:
        if self._history is None:
            return
        try:
            self._history.append(HistoryEntry(_iso(self._clock()), r.id, r.message, outcome, detail))
        except Exception:
            log.exception("Could not write history")

    def _save(self) -> None:
        try:
            self._store.save(self._reminders)
        except Exception:
            log.exception("Could not save reminders")

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                log.exception("Reminder listener failed")
