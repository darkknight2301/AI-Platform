"""Checks the files shipped with the project (no GUI needed)."""
import json
import unittest
import wave
from datetime import datetime

from app.characters.base_character import CharacterContext
from app.characters.character_manager import CharacterManager
from app.config import Config
from app.storage.reminder_store import JsonReminderStore
from app.utils.paths import default_paths
from app.utils.sound import EVENTS, SoundPlayer
from tests.helpers import TempDirTestCase

PATHS = default_paths()


class BundledContentTests(TempDirTestCase):
    def test_builtin_and_sample_characters_discovered(self):
        m = CharacterManager(PATHS.builtin_characters_dir, PATHS.user_characters_dir,
                             CharacterContext(Config()), lambda: "default_character")
        self.assertEqual([i.id for i in m.list()], ["default_character", "robot"])

    def test_robot_manifest_references_existing_frames(self):
        folder = PATHS.user_characters_dir / "robot"
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        for name, spec in manifest["animations"].items():
            self.assertTrue(list(folder.glob(spec["pattern"])), name)

    def test_all_sounds_present_and_valid(self):
        player = SoundPlayer(PATHS.sounds_dir)
        for event in EVENTS:
            path = player.find(event)
            self.assertIsNotNone(path, event)
            with wave.open(str(path)) as w:
                self.assertGreater(w.getnframes(), 0)

    def test_missing_sound_is_skipped_quietly(self):
        self.assertFalse(SoundPlayer(self.tmp).play("enter"))

    def test_example_reminders_load_and_schedule(self):
        data = (PATHS.data_dir / "reminders.example.json").read_text(encoding="utf-8")
        (self.tmp / "reminders.json").write_text(data, encoding="utf-8")
        m = self.make_manager()
        self.assertEqual(len(m.list()), 6)
        self.assertTrue(all(r.next_due for r in m.list()))
        self.assertTrue(any("\U0001F4A7" in r.message for r in m.list()))

    def test_default_config_file_is_valid(self):
        cfg = Config.load(PATHS.config_file)
        self.assertEqual(cfg.application.character_position, "bottom_right")


if __name__ == "__main__":
    unittest.main()
