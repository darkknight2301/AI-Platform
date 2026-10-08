import unittest
from datetime import datetime

from app.reminders.errors import (DuplicateReminderError, InvalidReminderError,
                                  ReminderNotFoundError)
from app.reminders.reminder import Reminder
from tests.helpers import TempDirTestCase


def water(**kw):
    kw.setdefault("message", "Drink Water")
    kw.setdefault("time", "10:30")
    return Reminder(**kw)


class ManagerCrudTests(TempDirTestCase):
    def test_create_schedules_next_due(self):
        m = self.make_manager()
        r = m.add(water())
        self.assertEqual(r.next_due, "2026-10-08T10:30:00")
        self.assertEqual(r.status, "scheduled")

    def test_create_after_time_rolls_to_tomorrow(self):
        m = self.make_manager()
        self.assertEqual(m.add(water(time="09:00")).next_due, "2026-10-09T09:00:00")

    def test_once_in_past_rejected(self):
        m = self.make_manager()
        with self.assertRaises(InvalidReminderError):
            m.add(water(repeat="once", date="2026-10-07"))

    def test_once_without_date_is_pinned(self):
        m = self.make_manager()
        self.assertEqual(m.add(water(repeat="once")).date, "2026-10-08")

    def test_edit(self):
        m = self.make_manager()
        r = m.add(water())
        r.message, r.time = "Hydrate", "11:15"
        updated = m.update(r)
        self.assertEqual(updated.next_due, "2026-10-08T11:15:00")
        self.assertEqual(m.get(r.id).message, "Hydrate")

    def test_edit_unknown_raises(self):
        m = self.make_manager()
        with self.assertRaises(ReminderNotFoundError):
            m.update(water())

    def test_delete(self):
        m = self.make_manager()
        r = m.add(water())
        m.delete(r.id)
        self.assertEqual(m.list(), [])
        with self.assertRaises(ReminderNotFoundError):
            m.delete(r.id)

    def test_enable_disable(self):
        m = self.make_manager()
        r = m.add(water())
        off = m.set_enabled(r.id, False)
        self.assertEqual((off.enabled, off.next_due, off.status), (False, None, "disabled"))
        self.clock.now = datetime(2026, 10, 8, 12, 0)
        on = m.set_enabled(r.id, True)
        self.assertEqual(on.next_due, "2026-10-09T10:30:00")

    def test_disabled_reminder_never_fires(self):
        m = self.make_manager()
        r = m.add(water(enabled=False))
        self.clock.now = datetime(2026, 10, 9, 10, 30)
        self.assertEqual(m.claim_due(), [])
        self.assertEqual(m.get(r.id).status, "disabled")

    def test_duplicate_conflict(self):
        m = self.make_manager()
        m.add(water())
        with self.assertRaises(DuplicateReminderError):
            m.add(water(message="  drink water "))
        m.add(water(time="11:00"))                             # different time is fine
        m.add(water(repeat="weekly", weekdays=[1]))            # different schedule is fine

    def test_duplicate_on_edit_but_not_self(self):
        m = self.make_manager()
        a = m.add(water())
        b = m.add(water(time="11:00"))
        m.update(a)                                            # unchanged: not its own duplicate
        b.time = "10:30"
        with self.assertRaises(DuplicateReminderError):
            m.update(b)


class ManagerLifecycleTests(TempDirTestCase):
    def test_done_reschedules_daily(self):
        m = self.make_manager()
        r = m.add(water())
        self.clock.now = datetime(2026, 10, 8, 10, 30, 2)
        (due,) = m.claim_due()
        self.assertEqual(m.get(due.id).status, "active")
        m.complete(due.id)
        after = m.get(r.id)
        self.assertEqual((after.status, after.next_due), ("completed", "2026-10-09T10:30:00"))

    def test_done_disables_one_shot(self):
        m = self.make_manager()
        r = m.add(water(repeat="once"))
        self.clock.now = datetime(2026, 10, 8, 10, 30, 2)
        m.claim_due()
        m.complete(r.id)
        after = m.get(r.id)
        self.assertEqual((after.enabled, after.status, after.next_due), (False, "completed", None))

    def test_snooze_reschedules_and_returns(self):
        m = self.make_manager()
        r = m.add(water(snooze_minutes=15))
        self.clock.now = datetime(2026, 10, 8, 10, 30, 2)
        m.claim_due()
        m.snooze(r.id)
        self.assertEqual(m.get(r.id).next_due, "2026-10-08T10:45:02")
        self.clock.now = datetime(2026, 10, 8, 10, 44)
        self.assertEqual(m.claim_due(), [])
        self.clock.now = datetime(2026, 10, 8, 10, 45, 3)
        self.assertEqual(len(m.claim_due()), 1)

    def test_snooze_invalid_minutes(self):
        m = self.make_manager()
        r = m.add(water())
        with self.assertRaises(InvalidReminderError):
            m.snooze(r.id, 0)

    def test_unknown_id_is_a_noop(self):                      # test reminders aren't stored
        m = self.make_manager()
        self.assertFalse(m.complete("__test__"))
        self.assertFalse(m.snooze("__test__"))

    def test_pause_blocks_firing_until_resumed(self):
        m = self.make_manager()
        m.add(water())
        m.set_paused(True)
        self.clock.now = datetime(2026, 10, 8, 10, 31)
        self.assertEqual(m.claim_due(), [])
        m.set_paused(False)
        self.assertEqual(len(m.claim_due()), 1)

    def test_multiple_due_ordered_by_time(self):
        m = self.make_manager()
        m.add(water(message="B", time="10:20"))
        m.add(water(message="A", time="10:10"))
        self.clock.now = datetime(2026, 10, 8, 10, 0)
        m.add(water(message="C", time="10:30"))
        self.clock.now = datetime(2026, 10, 8, 10, 31)
        self.assertEqual([r.message for r in m.claim_due()], ["A", "B", "C"])

    def test_missed_within_grace_still_fires(self):
        m = self.make_manager()
        m.add(water())
        self.clock.now = datetime(2026, 10, 8, 10, 50)
        self.assertEqual(len(m.claim_due()), 1)

    def test_missed_beyond_grace_is_recorded_not_shown(self):
        m = self.make_manager()
        r = m.add(water())
        self.clock.now = datetime(2026, 10, 8, 14, 0)         # app was closed for hours
        self.assertEqual(m.claim_due(), [])
        after = m.get(r.id)
        self.assertEqual((after.status, after.next_due), ("missed", "2026-10-09T10:30:00"))
        self.assertEqual(m.history()[0].outcome, "missed")

    def test_reconcile_on_restart(self):
        m = self.make_manager()
        m.add(water())
        m2 = self.make_manager(clock=type(self.clock)(datetime(2026, 10, 8, 18, 0)))
        self.assertEqual(m2.reconcile(), 1)

    def test_history_records_flow(self):
        m = self.make_manager()
        r = m.add(water())
        self.clock.now = datetime(2026, 10, 8, 10, 30, 1)
        m.claim_due()
        m.snooze(r.id)
        self.assertEqual([h.outcome for h in m.history()], ["snoozed", "fired"])

    def test_listener_notified(self):
        m = self.make_manager()
        calls = []
        m.add_listener(lambda: calls.append(1))
        m.add(water())
        self.assertTrue(calls)


if __name__ == "__main__":
    unittest.main()
