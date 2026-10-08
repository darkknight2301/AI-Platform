import json
import unittest
from datetime import datetime

from app.characters.base_character import (ACTION_COMPLETED, ACTION_SNOOZED, BaseCharacter,
                                           CharacterContext, CharacterInfo, CharacterState,
                                           CharacterStateMachine, InvalidTransition)
from app.characters.character_controller import CharacterController
from app.characters.character_manager import CharacterLoadError, CharacterManager
from app.config import Config
from app.reminders.reminder import Reminder
from tests.helpers import TempDirTestCase

S = CharacterState


class StateMachineTests(unittest.TestCase):
    def test_happy_path(self):
        sm = CharacterStateMachine()
        for s in (S.ENTERING, S.IDLE, S.REMINDER, S.HAPPY, S.EXITING, S.HIDDEN):
            sm.transition(s)
        self.assertEqual(sm.state, S.HIDDEN)

    def test_snooze_path(self):
        sm = CharacterStateMachine()
        for s in (S.ENTERING, S.REMINDER, S.ANGRY, S.EXITING, S.HIDDEN):
            sm.transition(s)

    def test_illegal_transitions(self):
        sm = CharacterStateMachine()
        for bad in (S.HAPPY, S.ANGRY, S.EXITING, S.REMINDER, S.IDLE):
            with self.assertRaises(InvalidTransition):
                sm.transition(bad)
        sm.transition(S.ENTERING)
        with self.assertRaises(InvalidTransition):
            sm.transition(S.HAPPY)                 # must be asked first

    def test_reset(self):
        sm = CharacterStateMachine()
        sm.transition(S.ENTERING)
        sm.reset()
        self.assertEqual(sm.state, S.HIDDEN)


class FakeCharacter(BaseCharacter):
    """Instant character used to test the controller without any GUI."""

    def __init__(self, info, context):
        super().__init__(info, context)
        self.log = []

    def show_reminder(self, reminder):
        self._reminder = reminder
        self.log.append("show:" + reminder.message)
        self._set_state(S.ENTERING)
        self._set_state(S.REMINDER)

    def react(self, outcome):
        self.log.append("react:" + outcome)
        self._set_state(S.HAPPY if outcome == ACTION_COMPLETED else S.ANGRY)
        self._set_state(S.EXITING)
        self._set_state(S.HIDDEN)
        self._notify_finished()

    def hide(self, immediate=False):
        self.log.append("hide")


class FakeCharacters:
    def __init__(self, character):
        self.character = character

    def create(self, _id):
        return self.character


class FakeSounds:
    def __init__(self):
        self.events = []

    def play(self, event, dirs=()):
        self.events.append(event)


class ControllerTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.manager = self.make_manager()
        info = CharacterInfo("fake", "Fake", self.tmp)
        self.char = FakeCharacter(info, CharacterContext(Config()))
        self.sounds = FakeSounds()
        self.controller = CharacterController(self.manager, FakeCharacters(self.char), Config(),
                                              self.sounds)

    def _due(self, **kw):
        self.manager.add(Reminder(message=kw.pop("message", "Drink Water"), time="10:30", **kw))
        self.clock.now = datetime(2026, 10, 8, 10, 30, 1)
        return self.manager.claim_due()

    def test_done_flow(self):
        (r,) = self._due()
        self.controller.present(r)
        self.char._emit_action(ACTION_COMPLETED)
        self.assertEqual(self.char.log, ["show:Drink Water", "react:completed"])
        self.assertEqual(self.manager.get(r.id).status, "completed")
        self.assertEqual(self.sounds.events, ["enter", "reminder", "happy", "exit"])
        self.assertFalse(self.controller.busy)

    def test_snooze_flow_reschedules(self):
        (r,) = self._due(snooze_minutes=5)
        self.controller.present(r)
        self.char._emit_action(ACTION_SNOOZED)
        after = self.manager.get(r.id)
        self.assertEqual((after.status, after.next_due), ("snoozed", "2026-10-08T10:35:01"))
        self.assertIn("angry", self.sounds.events)

    def test_sound_disabled_per_reminder_and_globally(self):
        (r,) = self._due(sound_enabled=False)
        self.controller.present(r)
        self.char._emit_action(ACTION_COMPLETED)
        self.assertEqual(self.sounds.events, [])
        self.controller._config.application.sound_enabled = False
        self.assertEqual(self.sounds.events, [])

    def test_queue_shows_one_character_at_a_time(self):
        a = Reminder(message="A", time="10:30")
        b = Reminder(message="B", time="10:30")
        self.controller.present(a)
        self.controller.present(b)
        self.assertEqual(self.char.log, ["show:A"])
        self.char._emit_action(ACTION_COMPLETED)
        self.assertEqual(self.char.log[-2:], ["react:completed", "show:B"])

    def test_test_reminder_not_in_manager_is_safe(self):
        self.controller.present(Reminder(message="test", time="10:00", id="__test__"))
        self.char._emit_action(ACTION_SNOOZED)               # no exception, nothing stored
        self.assertEqual(self.manager.list(), [])

    def test_character_crash_snoozes_instead_of_looping(self):
        (r,) = self._due()

        def boom(_):
            raise RuntimeError("bad art")
        self.char.show_reminder = boom
        self.controller.present(r)
        self.assertEqual(self.manager.get(r.id).status, "snoozed")
        self.assertFalse(self.controller.busy)


class CharacterManagerTests(TempDirTestCase):
    def _char(self, root, folder, **manifest):
        d = root / folder
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return d

    def _manager(self, default="a"):
        builtin, user = self.tmp / "builtin", self.tmp / "user"
        builtin.mkdir(), user.mkdir()
        self._char(builtin, "a", id="a", name="Alpha")
        self._char(user, "b", id="b", name="Beta")
        (user / "broken").mkdir()
        (user / "broken" / "manifest.json").write_text("{nope", encoding="utf-8")
        self._char(user, "nameless")                         # id falls back to folder name
        return CharacterManager(builtin, user, CharacterContext(Config()), lambda: default)

    def test_discovery_skips_broken_manifests(self):
        ids = [i.id for i in self._manager().list()]
        self.assertEqual(ids, ["a", "b", "nameless"])

    def test_unknown_and_empty_id_resolve_to_default(self):
        m = self._manager()
        self.assertEqual(m.resolve_id(""), "a")
        self.assertEqual(m.resolve_id("dog"), "a")
        self.assertEqual(m.resolve_id("b"), "b")

    def test_user_character_overrides_builtin_with_same_id(self):
        m = self._manager()
        self._char(self.tmp / "user", "alpha2", id="a", name="Override")
        m.discover()
        self.assertEqual(m.get_info("a").name, "Override")

    def test_code_character_loaded_from_entry_and_failure_falls_back(self):
        user = self.tmp / "user"
        m = self._manager()
        good = self._char(user, "good", id="good", name="Good", entry="character.py")
        (good / "character.py").write_text(
            "from app.characters.base_character import BaseCharacter\n"
            "class C(BaseCharacter):\n"
            "    def show_reminder(self, r): pass\n"
            "    def react(self, o): pass\n"
            "    def hide(self, immediate=False): pass\n"
            "def create_character(info, context): return C(info, context)\n", encoding="utf-8")
        bad = self._char(user, "bad", id="bad", name="Bad", entry="character.py")
        (bad / "character.py").write_text("raise RuntimeError('broken plugin')\n", encoding="utf-8")
        m.discover()
        self.assertEqual(m.create("good").info.id, "good")
        self.assertIs(m.create("good"), m.create("good"))    # cached
        # 'a' has no entry -> would need Qt; use another code character as the default instead
        m2 = CharacterManager(self.tmp / "builtin", user, CharacterContext(Config()), lambda: "good")
        self.assertEqual(m2.create("bad").info.id, "good")   # broken plugin -> default

    def test_no_characters_raises(self):
        empty = CharacterManager(self.tmp / "x", self.tmp / "y", CharacterContext(Config()), lambda: "a")
        with self.assertRaises(CharacterLoadError):
            empty.create("")


if __name__ == "__main__":
    unittest.main()
