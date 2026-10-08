"""CharacterController: turns Reminder events into character performances.

It sits between the reminder engine and characters, queues simultaneous
reminders (one character on screen at a time), applies the user's action to the
ReminderManager and triggers sounds. Qt-free; the `defer` hook lets the GUI layer
schedule the next reminder on its event loop.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from app.characters.base_character import (ACTION_COMPLETED, ACTION_SNOOZED, BaseCharacter,
                                           CharacterListener, CharacterState)
from app.characters.character_manager import CharacterLoadError, CharacterManager
from app.config import Config
from app.reminders.reminder import Reminder
from app.reminders.reminder_manager import ReminderManager

log = logging.getLogger(__name__)

_SOUND_FOR_STATE = {
    CharacterState.ENTERING: "enter",
    CharacterState.REMINDER: "reminder",
    CharacterState.HAPPY: "happy",
    CharacterState.ANGRY: "angry",
    CharacterState.EXITING: "exit",
}


class CharacterController(CharacterListener):
    def __init__(self, manager: ReminderManager, characters: CharacterManager, config: Config,
                 sounds=None, defer: Optional[Callable[[Callable[[], None]], None]] = None):
        self._manager = manager
        self._characters = characters
        self._config = config
        self._sounds = sounds
        self._defer = defer or (lambda fn: fn())
        self._queue: List[Reminder] = []
        self._current: Optional[Tuple[Reminder, BaseCharacter]] = None

    # ---- API used by the application ----------------------------------------------
    def present(self, reminder: Reminder) -> None:
        if self._current and self._current[0].id == reminder.id:
            return
        if any(q.id == reminder.id for q in self._queue):
            return
        self._queue.append(reminder)
        self._pump()

    @property
    def busy(self) -> bool:
        return self._current is not None

    def shutdown(self) -> None:
        self._queue.clear()
        if self._current:
            try:
                self._current[1].hide(immediate=True)
            except Exception:
                log.exception("Error while hiding the character")
        self._current = None

    # ---- internals ---------------------------------------------------------------
    def _pump(self) -> None:
        if self._current is not None or not self._queue:
            return
        reminder = self._queue.pop(0)
        try:
            character = self._characters.create(reminder.character)
        except CharacterLoadError:
            log.exception("No usable character; postponing '%s' by one minute", reminder.message)
            self._manager.snooze(reminder.id, 1)
            self._defer(self._pump)
            return
        self._current = (reminder, character)
        character.set_listener(self)
        try:
            character.show_reminder(reminder)
        except Exception:
            log.exception("Character '%s' failed to show a reminder", character.info.id)
            self._abort_current(snooze=True)

    def _abort_current(self, snooze: bool) -> None:
        if self._current is None:
            return
        reminder, character = self._current
        self._current = None
        try:
            character.hide(immediate=True)
        except Exception:
            log.exception("Character failed to hide")
        if snooze:
            self._manager.snooze(reminder.id, 1)
        self._defer(self._pump)

    # ---- CharacterListener -------------------------------------------------------
    def on_user_action(self, character, reminder, action) -> None:
        try:
            if action == ACTION_COMPLETED:
                self._manager.complete(reminder.id)
            elif action == ACTION_SNOOZED:
                self._manager.snooze(reminder.id)
        except Exception:
            log.exception("Could not apply action '%s' to reminder %s", action, reminder.id)
        try:
            character.react(action)
        except Exception:
            log.exception("Character failed to react; hiding it")
            character.hide(immediate=True)

    def on_state_changed(self, character, state, reminder) -> None:
        event = _SOUND_FOR_STATE.get(state)
        if not (event and self._sounds and self._config.application.sound_enabled):
            return
        if reminder is not None and not reminder.sound_enabled:
            return
        try:
            self._sounds.play(event, character.sound_dirs)
        except Exception:
            log.exception("Sound playback failed")

    def on_finished(self, character, reminder) -> None:
        if self._current and self._current[1] is character:
            self._current = None
            self._defer(self._pump)
