"""Application wiring: config -> reminders -> scheduler -> characters -> Qt."""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from app.config import Config
from app.utils import startup
from app.utils.logging_setup import setup_logging
from app.utils.paths import default_paths

log = logging.getLogger("app.main")
TEST_ID = "__test__"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Desktop Reminder")
    parser.add_argument("--open", action="store_true", help="open the reminders window at start")
    parser.add_argument("--test", action="store_true", help="play a test reminder at start")
    args = parser.parse_args(argv)

    paths = default_paths()
    paths.ensure()
    setup_logging(paths.logs_dir)
    log.info("Starting Desktop Reminder (root: %s)", paths.root)

    try:
        from PySide6.QtCore import QLockFile, QObject, QTimer, Signal, Slot
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        log.error("PySide6 is not installed. Run: pip install -r requirements.txt")
        print("PySide6 is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 2

    from app.characters.base_character import CharacterContext
    from app.characters.character_controller import CharacterController
    from app.characters.character_manager import CharacterManager
    from app.reminders.reminder import Reminder
    from app.reminders.reminder_manager import ReminderManager
    from app.reminders.scheduler import Scheduler
    from app.storage.reminder_store import JsonHistoryStore, JsonReminderStore
    from app.ui.settings_window import TAB_SETTINGS, SettingsWindow
    from app.ui.tray import Tray, build_icon
    from app.utils.sound import SoundPlayer

    config = Config.load(paths.config_file)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Desktop Reminder")
    app.setQuitOnLastWindowClosed(False)          # lives in the tray
    app.setWindowIcon(build_icon())
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl+C works when run from a console

    lock = QLockFile(str(Path(tempfile.gettempdir()) / "desktop_reminder.lock"))
    lock.setStaleLockTime(15000)
    if not lock.tryLock(200):
        log.warning("Another instance is already running; exiting")
        QMessageBox.information(None, "Desktop Reminder", "Desktop Reminder is already running "
                                "(look for the tray icon).")
        return 0

    manager = ReminderManager(JsonReminderStore(paths.reminders_file),
                              JsonHistoryStore(paths.history_file),
                              missed_grace=timedelta(minutes=config.reminder.missed_grace_minutes))
    manager.reconcile()
    characters = CharacterManager(paths.builtin_characters_dir, paths.user_characters_dir,
                                  CharacterContext(config), lambda: config.application.default_character)
    controller = CharacterController(manager, characters, config, SoundPlayer(paths.sounds_dir),
                                     defer=lambda fn: QTimer.singleShot(400, fn))

    def save_config() -> None:
        manager.set_missed_grace(timedelta(minutes=config.reminder.missed_grace_minutes))
        config.save(paths.config_file)

    def test_character(character_id: Optional[str] = None) -> None:
        now = datetime.now()
        controller.present(Reminder(message="Drink Water \U0001F4A7", time=now.strftime("%H:%M"),
                                    id=TEST_ID, character=character_id or "",
                                    snooze_minutes=config.reminder.default_snooze_minutes))

    window = SettingsWindow(manager, characters, config, save_config, test_character,
                            lambda enabled: startup.set_enabled(enabled, paths.root),
                            startup.is_enabled())

    class UiBridge(QObject):
        """Receives scheduler-thread events; queued signals land on the GUI thread."""
        due = Signal(object)
        changed = Signal()

        def __init__(self) -> None:
            super().__init__()
            self.due.connect(self._on_due)
            self.changed.connect(window.refresh)

        @Slot(object)
        def _on_due(self, reminders) -> None:
            for r in reminders:
                controller.present(r)

    bridge = UiBridge()
    manager.add_listener(bridge.changed.emit)
    scheduler = Scheduler(manager, bridge.due.emit)

    def quit_app() -> None:
        app.quit()

    tray = Tray(build_icon(), window.show_and_raise, window.add_reminder, test_character,
                manager.set_paused, lambda: window.show_tab(TAB_SETTINGS), quit_app)
    if tray.icon.isSystemTrayAvailable():
        tray.show()
        tray.notify_running()
    else:
        log.warning("No system tray available; opening the window instead")
        window.show_and_raise()

    if args.open or not manager.list():
        window.show_and_raise()
    if args.test:
        QTimer.singleShot(800, test_character)

    scheduler.start()
    try:
        code = app.exec()
    finally:
        log.info("Shutting down")
        scheduler.stop()
        controller.shutdown()
        characters.shutdown()
        tray.hide()
        lock.unlock()
    return code
