import unittest

from app.reminders.errors import InvalidReminderError
from app.reminders.reminder import Reminder


class ReminderModelTests(unittest.TestCase):
    def test_creation_normalises_fields(self):
        r = Reminder(message="  Drink Water  ", time="9:05")
        r.validate()
        self.assertEqual(r.message, "Drink Water")
        self.assertEqual(r.time, "09:05")

    def test_accepts_12_hour_time(self):
        for text, expected in (("10:30 AM", "10:30"), ("1:00 pm", "13:00"), ("12:00 AM", "00:00")):
            r = Reminder(message="x", time=text)
            r.validate()
            self.assertEqual(r.time, expected)

    def test_invalid_values_rejected(self):
        bad = [dict(message="", time="10:00"), dict(message="x", time="25:00"),
               dict(message="x", time="abc"), dict(message="x", time="10:00", repeat="monthly"),
               dict(message="x", time="10:00", repeat="weekly"),
               dict(message="x", time="10:00", snooze_minutes=0),
               dict(message="x", time="10:00", interval_minutes=0),
               dict(message="x", time="10:00", date="2026-13-40"),
               dict(message="x" * 500, time="10:00")]
        for kwargs in bad:
            with self.assertRaises(InvalidReminderError, msg=str(kwargs)):
                Reminder(**kwargs).validate()

    def test_from_dict_roundtrip_and_unknown_keys(self):
        r = Reminder(message="Lunch", time="13:00", repeat="weekly", weekdays=[0, 2])
        r.validate()
        data = r.to_dict()
        data["future_field"] = 1
        self.assertEqual(Reminder.from_dict(data).to_dict(), r.to_dict())

    def test_from_dict_rejects_garbage(self):
        for raw in (None, [], {"message": "x"}, {"message": "x", "time": "bad"},
                    {"message": "x", "time": "10:00", "snooze_minutes": "lots"}):
            with self.assertRaises(InvalidReminderError):
                Reminder.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
