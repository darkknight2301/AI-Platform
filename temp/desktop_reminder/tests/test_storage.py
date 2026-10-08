import unittest
from datetime import datetime

from app.reminders.reminder import Reminder
from app.storage.reminder_store import JsonHistoryStore, JsonReminderStore
from tests.helpers import FakeClock, TempDirTestCase


class StorageTests(TempDirTestCase):
    def test_persistence_across_restart(self):
        m = self.make_manager()
        r = m.add(Reminder(message="Walk", time="18:00", repeat="weekly", weekdays=[0, 1]))
        m.set_enabled(r.id, False)
        again = self.make_manager()
        (loaded,) = again.list()
        self.assertEqual((loaded.id, loaded.message, loaded.weekdays, loaded.enabled),
                         (r.id, "Walk", [0, 1], False))

    def test_missing_file_is_empty(self):
        self.assertEqual(JsonReminderStore(self.tmp / "nope.json").load(), [])

    def test_corrupt_file_is_moved_aside(self):
        path = self.tmp / "reminders.json"
        path.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(JsonReminderStore(path).load(), [])
        self.assertFalse(path.exists())
        self.assertEqual(len(list(self.tmp.glob("reminders.json.corrupt-*"))), 1)

    def test_one_bad_entry_does_not_lose_others(self):
        good = Reminder(message="Lunch", time="13:00")
        good.validate()
        path = self.write_json("reminders.json", {"reminders": [
            good.to_dict(), {"message": "bad", "time": "99:99"}, "garbage", good.to_dict()]})
        loaded = JsonReminderStore(path).load()
        self.assertEqual([r.message for r in loaded], ["Lunch"])   # bad ones and duplicate id dropped

    def test_manager_survives_corrupt_store(self):
        (self.tmp / "reminders.json").write_text("\x00\x01", encoding="utf-8")
        m = self.make_manager()
        self.assertEqual(m.list(), [])
        m.add(Reminder(message="Still works", time="12:00"))
        self.assertEqual(len(self.make_manager().list()), 1)

    def test_load_schedules_entries_without_next_due(self):
        self.write_json("reminders.json", [{"message": "Lunch", "time": "13:00"}])
        m = self.make_manager()
        self.assertEqual(m.list()[0].next_due, "2026-10-08T13:00:00")

    def test_active_status_reset_after_crash(self):
        m = self.make_manager()
        m.add(Reminder(message="x", time="10:00", repeat="daily"))
        self.clock.now = datetime(2026, 10, 9, 10, 0, 1)
        m.claim_due()                                          # persisted as 'active'
        again = self.make_manager(clock=FakeClock(datetime(2026, 10, 9, 10, 1)))
        self.assertEqual(again.list()[0].status, "scheduled")
        self.assertEqual(len(again.claim_due()), 1)            # still shown after restart

    def test_history_is_capped_and_persisted(self):
        store = JsonHistoryStore(self.tmp / "h.json", max_entries=3)
        from app.reminders.reminder import HistoryEntry
        for i in range(5):
            store.append(HistoryEntry("t%d" % i, "id", "m", "fired"))
        reloaded = JsonHistoryStore(self.tmp / "h.json", max_entries=3).load()
        self.assertEqual([e.timestamp for e in reloaded], ["t2", "t3", "t4"])


if __name__ == "__main__":
    unittest.main()
