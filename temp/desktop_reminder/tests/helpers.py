import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.reminders.reminder_manager import ReminderManager
from app.storage.reminder_store import JsonHistoryStore, JsonReminderStore


class FakeClock:
    def __init__(self, now=datetime(2026, 10, 8, 10, 0, 0)):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dr_test_"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    def make_manager(self, clock=None, grace_minutes=30):
        self.clock = clock or FakeClock()
        self.store = JsonReminderStore(self.tmp / "reminders.json")
        self.history = JsonHistoryStore(self.tmp / "history.json")
        return ReminderManager(self.store, self.history, clock=self.clock,
                               missed_grace=timedelta(minutes=grace_minutes))

    def write_json(self, name, payload):
        path = self.tmp / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
