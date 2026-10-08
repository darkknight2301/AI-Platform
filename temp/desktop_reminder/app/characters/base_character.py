"""Character contract. Qt-free on purpose: the reminder engine, the controller and
the tests only ever see this interface."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import Config
from app.reminders.reminder import Reminder

log = logging.getLogger(__name__)

ACTION_COMPLETED = "completed"
ACTION_SNOOZED = "snoozed"


class CharacterState(Enum):
    HIDDEN = "hidden"
    ENTERING = "entering"
    IDLE = "idle"
    REMINDER = "reminder"
    HAPPY = "happy"
    ANGRY = "angry"
    EXITING = "exiting"


S = CharacterState
ALLOWED_TRANSITIONS = {
    S.HIDDEN: {S.ENTERING},
    S.ENTERING: {S.IDLE, S.REMINDER, S.EXITING},
    S.IDLE: {S.REMINDER, S.EXITING},
    S.REMINDER: {S.HAPPY, S.ANGRY, S.EXITING},
    S.HAPPY: {S.EXITING},
    S.ANGRY: {S.EXITING},
    S.EXITING: {S.HIDDEN},
}


class InvalidTransition(Exception):
    pass


class CharacterStateMachine:
    def __init__(self) -> None:
        self._state = S.HIDDEN

    @property
    def state(self) -> CharacterState:
        return self._state

    def can_transition(self, new: CharacterState) -> bool:
        return new in ALLOWED_TRANSITIONS[self._state]

    def transition(self, new: CharacterState) -> None:
        if not self.can_transition(new):
            raise InvalidTransition("%s -> %s" % (self._state.value, new.value))
        self._state = new

    def reset(self) -> None:
        """Hard reset (used when a character is aborted)."""
        self._state = S.HIDDEN


@dataclass
class CharacterInfo:
    id: str
    name: str
    path: Path
    manifest: Dict[str, Any] = field(default_factory=dict)
    builtin: bool = False


@dataclass
class CharacterContext:
    """What a character may rely on from the host application."""
    config: Config


class CharacterListener:
    """Implemented by the CharacterController. All hooks are optional no-ops."""

    def on_user_action(self, character: "BaseCharacter", reminder: Reminder, action: str) -> None:
        pass

    def on_state_changed(self, character: "BaseCharacter", state: CharacterState,
                         reminder: Optional[Reminder]) -> None:
        pass

    def on_finished(self, character: "BaseCharacter", reminder: Optional[Reminder]) -> None:
        pass


class BaseCharacter(ABC):
    """Every character (placeholder, robot, cat...) implements this."""

    def __init__(self, info: CharacterInfo, context: CharacterContext):
        self.info = info
        self.context = context
        self._machine = CharacterStateMachine()
        self._listener: Optional[CharacterListener] = None
        self._reminder: Optional[Reminder] = None

    # ---- contract used by the controller -------------------------------------
    @abstractmethod
    def show_reminder(self, reminder: Reminder) -> None:
        """Enter the screen and present the reminder (non-blocking)."""

    @abstractmethod
    def react(self, outcome: str) -> None:
        """React to ACTION_COMPLETED / ACTION_SNOOZED, then leave."""

    @abstractmethod
    def hide(self, immediate: bool = False) -> None:
        """Leave gracefully, or vanish at once when ``immediate``."""

    # ---- shared plumbing ------------------------------------------------------
    @property
    def state(self) -> CharacterState:
        return self._machine.state

    @property
    def sound_dirs(self):
        """Optional per-character sound overrides (``<character>/sounds``)."""
        return [self.info.path / "sounds"]

    def set_listener(self, listener: Optional[CharacterListener]) -> None:
        self._listener = listener

    def _set_state(self, new: CharacterState) -> None:
        if new == self._machine.state:
            return
        try:
            self._machine.transition(new)
        except InvalidTransition as exc:
            log.warning("%s: unexpected transition %s; forcing", self.info.id, exc)
            self._machine._state = new
        if self._listener:
            self._listener.on_state_changed(self, new, self._reminder)

    def _emit_action(self, action: str) -> None:
        """Called by the character when the user clicked a button."""
        if self._reminder is None:
            return
        if self._listener:
            self._listener.on_user_action(self, self._reminder, action)
        else:
            self.react(action)

    def _notify_finished(self) -> None:
        reminder, self._reminder = self._reminder, None
        if self._listener:
            self._listener.on_finished(self, reminder)
