import unittest
from datetime import datetime, timedelta

from app.reminders.reminder import Reminder
from app.reminders.scheduler import (Scheduler, advance_after_fire, next_occurrence,
                                     snooze_until)
from tests.helpers import FakeClock, TempDirTestCase


def make(**kw):
    kw.setdefault("message", "x")
    kw.setdefault("time", "10:30")
    r = Reminder(**kw)
    r.validate()
    return r


class RepeatCalculationTests(unittest.TestCase):
    def test_daily_before_and_after_time(self):
        r = make(repeat="daily")
        self.assertEqual(next_occurrence(r, datetime(2026, 10, 8, 9, 0)), datetime(2026, 10, 8, 10, 30))
        self.assertEqual(next_occurrence(r, datetime(2026, 10, 8, 10, 30)), datetime(2026, 10, 9, 10, 30))

    def test_once_with_date(self):
        r = make(repeat="once", date="2026-10-10")
        self.assertEqual(next_occurrence(r, datetime(2026, 10, 8, 0, 0)), datetime(2026, 10, 10, 10, 30))
        self.assertIsNone(next_occurrence(r, datetime(2026, 10, 11, 0, 0)))

    def test_weekly_picks_next_selected_weekday(self):
        r = make(repeat="weekly", weekdays=[0, 4])           # Mon, Fri
        thursday = datetime(2026, 10, 8, 12, 0)               # 2026-10-08 is a Thursday
        self.assertEqual(next_occurrence(r, thursday), datetime(2026, 10, 9, 10, 30))
        friday_after = datetime(2026, 10, 9, 11, 0)
        self.assertEqual(next_occurrence(r, friday_after), datetime(2026, 10, 12, 10, 30))

    def test_weekly_same_day_later_time(self):
        r = make(repeat="weekly", weekdays=[3])               # Thursday
        self.assertEqual(next_occurrence(r, datetime(2026, 10, 8, 8, 0)), datetime(2026, 10, 8, 10, 30))

    def test_interval_advances_in_steps_and_skips_past(self):
        r = make(repeat="interval", interval_minutes=45)
        r.next_due = "2026-10-08T10:30:00"
        self.assertEqual(advance_after_fire(r, datetime(2026, 10, 8, 10, 31)), datetime(2026, 10, 8, 11, 15))
        # slots are 10:30, 11:15, 12:00, 12:45 ... the next one strictly after 12:00 is 12:45
        self.assertEqual(advance_after_fire(r, datetime(2026, 10, 8, 12, 0)), datetime(2026, 10, 8, 12, 45))

    def test_once_never_repeats(self):
        r = make(repeat="once", date="2026-10-08")
        r.next_due = "2026-10-08T10:30:00"
        self.assertIsNone(advance_after_fire(r, datetime(2026, 10, 8, 10, 31)))

    def test_snooze_calculation(self):
        now = datetime(2026, 10, 8, 10, 30, 45, 999)
        self.assertEqual(snooze_until(now, 15), datetime(2026, 10, 8, 10, 45, 45))


class SchedulerPollTests(TempDirTestCase):
    def test_poll_delivers_due_reminder_once(self):
        manager = self.make_manager()
        manager.add(Reminder(message="Drink Water", time="10:30"))
        delivered = []
        sched = Scheduler(manager, delivered.append, clock=self.clock)
        self.assertEqual(sched.poll(), [])
        self.clock.now = datetime(2026, 10, 8, 10, 30, 1)
        self.assertEqual(len(sched.poll()), 1)
        self.assertEqual(sched.poll(), [])                    # still showing: not re-fired
        self.assertEqual(len(delivered), 1)

    def test_callback_failure_releases_reminder(self):
        manager = self.make_manager()
        manager.add(Reminder(message="x", time="10:30"))
        self.clock.now = datetime(2026, 10, 8, 10, 30, 1)

        def boom(_):
            raise RuntimeError("ui exploded")
        sched = Scheduler(manager, boom, clock=self.clock)
        sched.poll()                                          # must not raise
        good = []
        Scheduler(manager, good.append, clock=self.clock).poll()
        self.assertEqual(len(good), 1)                        # fires again after release

    def test_manager_failure_does_not_raise(self):
        class Broken:
            def claim_due(self, now):
                raise RuntimeError("db gone")
        self.assertEqual(Scheduler(Broken(), lambda d: None).poll(), [])

    def test_thread_starts_and_stops(self):
        manager = self.make_manager()
        sched = Scheduler(manager, lambda d: None, poll_interval=0.01)
        sched.start()
        self.assertTrue(sched.running)
        sched.stop()
        self.assertFalse(sched.running)


if __name__ == "__main__":
    unittest.main()
