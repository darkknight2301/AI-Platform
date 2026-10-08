import unittest
from pathlib import Path

from app.config import Config
from app.utils import startup
from app.utils.geometry import Rect, plan_motion
from tests.helpers import TempDirTestCase


class ConfigTests(TempDirTestCase):
    def test_defaults_written_on_first_run(self):
        path = self.tmp / "config" / "config.yaml"
        cfg = Config.load(path)
        self.assertTrue(path.exists())
        self.assertEqual(cfg.reminder.default_snooze_minutes, 10)

    def test_roundtrip(self):
        path = self.tmp / "c.yaml"
        cfg = Config()
        cfg.application.sound_enabled = False
        cfg.reminder.default_snooze_minutes = 25
        cfg.save(path)
        again = Config.load(path)
        self.assertFalse(again.application.sound_enabled)
        self.assertEqual(again.reminder.default_snooze_minutes, 25)

    def test_invalid_values_fall_back(self):
        path = self.tmp / "c.yaml"
        path.write_text("application:\n  character_position: moon\n  sound_enabled: banana\n"
                        "reminder:\n  default_snooze_minutes: 99999\n", encoding="utf-8")
        cfg = Config.load(path)
        self.assertEqual(cfg.application.character_position, "bottom_right")
        self.assertTrue(cfg.application.sound_enabled)
        self.assertEqual(cfg.reminder.default_snooze_minutes, 1440)

    def test_corrupt_yaml_gives_defaults(self):
        path = self.tmp / "c.yaml"
        path.write_text("a: [unclosed", encoding="utf-8")
        self.assertEqual(Config.load(path).to_dict(), Config().to_dict())


class GeometryTests(unittest.TestCase):
    primary = Rect(0, 0, 1920, 1080)
    avail = Rect(0, 0, 1920, 1040)           # 40px taskbar

    def test_single_monitor_bottom_right_enters_from_right(self):
        p = plan_motion(self.primary, self.avail, [], (260, 300))
        self.assertEqual(p.side, "right")
        self.assertEqual(p.end, (1920 - 260 - 24, 1040 - 300 - 24))
        self.assertEqual(p.start, (1920, p.end[1]))

    def test_avoids_edge_shared_with_neighbour(self):
        right_neighbour = Rect(1920, 0, 1920, 1080)
        p = plan_motion(self.primary, self.avail, [right_neighbour], (260, 300))
        self.assertEqual(p.side, "left")
        self.assertEqual(p.start[0], -260)

    def test_falls_back_to_bottom_when_both_sides_taken(self):
        others = [Rect(1920, 0, 1920, 1080), Rect(-1920, 0, 1920, 1080)]
        p = plan_motion(self.primary, self.avail, others, (260, 300))
        self.assertEqual(p.side, "bottom")
        self.assertEqual(p.start[1], 1080)

    def test_bottom_left_and_center(self):
        self.assertEqual(plan_motion(self.primary, self.avail, [], (260, 300), "bottom_left").end[0], 24)
        self.assertEqual(plan_motion(self.primary, self.avail, [], (260, 300), "bottom_center").end[0], 830)

    def test_window_larger_than_screen_is_clamped(self):
        p = plan_motion(Rect(0, 0, 200, 200), Rect(0, 0, 200, 200), [], (400, 400))
        self.assertGreaterEqual(p.end[0], 0)
        self.assertGreaterEqual(p.end[1], 0)


class StartupTests(unittest.TestCase):
    def test_command_quotes_paths_and_points_to_run_py(self):
        cmd = startup.build_command(Path("C:/Apps/Desktop Reminder"), "C:/Python38/python.exe")
        self.assertTrue(cmd.startswith('"'))
        self.assertIn("run.py", cmd)
        self.assertEqual(cmd.count('"'), 4)


if __name__ == "__main__":
    unittest.main()
