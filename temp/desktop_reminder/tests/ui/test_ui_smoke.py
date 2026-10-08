"""GUI smoke tests. Skipped automatically when PySide6 is not installed.

Run headless:  QT_QPA_PLATFORM=offscreen python -m unittest tests.ui.test_ui_smoke
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:                                   # pragma: no cover
    HAVE_QT = False


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class CharacterFlowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build(self, character_id):
        from app.characters.base_character import CharacterContext, CharacterListener, CharacterState
        from app.characters.character_manager import CharacterManager
        from app.config import Config
        from app.reminders.reminder import Reminder
        from app.utils.paths import default_paths
        paths = default_paths()
        cfg = Config()
        cfg.animation.enter_duration = cfg.animation.exit_duration = 0.25
        cfg.animation.reaction_duration = 0.25
        manager = CharacterManager(paths.builtin_characters_dir, paths.user_characters_dir,
                                   CharacterContext(cfg), lambda: "default_character")
        events = []

        class Spy(CharacterListener):
            def on_state_changed(self, c, state, r):
                events.append(state)

            def on_user_action(self, c, r, action):
                c.react(action)

            def on_finished(self, c, r):
                events.append("finished")

        char = manager.create(character_id)
        char.set_listener(Spy())
        char.show_reminder(Reminder(message="Drink Water", time="10:30", id="t"))
        return char, events, CharacterState

    def _run(self, character_id, action):
        char, events, S = self._build(character_id)
        wait(1200)                                    # walk in + idle pause
        self.assertEqual(char.state, S.REMINDER)
        char._emit_action(action)
        wait(1500)                                    # reaction + walk away
        self.assertEqual(char.state, S.HIDDEN)
        return events, S

    def test_placeholder_done_flow(self):
        events, S = self._run("default_character", "completed")
        self.assertEqual(events, [S.ENTERING, S.IDLE, S.REMINDER, S.HAPPY, S.EXITING, S.HIDDEN, "finished"])

    def test_placeholder_snooze_flow(self):
        events, S = self._run("default_character", "snoozed")
        self.assertIn(S.ANGRY, events)

    def test_png_sequence_character_flow(self):
        events, S = self._run("robot", "completed")
        self.assertIn(S.HAPPY, events)

    def test_missing_art_degrades_instead_of_crashing(self):
        char, events, S = self._build("robot")
        char._animations = {}                          # simulate all art missing
        wait(1200)
        self.assertEqual(char.state, S.REMINDER)
        char.hide(immediate=True)
        self.assertEqual(char.state, S.HIDDEN)


if __name__ == "__main__":
    unittest.main()
