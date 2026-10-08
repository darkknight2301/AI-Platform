"""SpriteCharacter: the generic, manifest-driven character.

Most new characters need *no code*: drop a folder with manifest.json + art into
``assets/characters/``. Characters that need custom drawing subclass this and
override ``load_animations`` (see the built-in default_character).
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from PySide6.QtCore import QPoint, QSize, QTimer

from app.characters.animation import Animation, PlaceholderAnimation
from app.characters.animation_loader import AnimationLoadError, build_animation
from app.characters.base_character import (ACTION_COMPLETED, ACTION_SNOOZED, BaseCharacter,
                                           CharacterContext, CharacterInfo, CharacterState)
from app.reminders.reminder import Reminder
from app.ui.desktop_overlay import DesktopOverlay, plan_for_screen

log = logging.getLogger(__name__)
S = CharacterState

# If an animation is missing the character falls back along this chain.
FALLBACKS = {"reminder": "idle", "happy": "idle", "angry": "idle", "sleep": "idle",
             "idle": "walk", "walk": ""}
IDLE_PAUSE_MS = 350


class SpriteCharacter(BaseCharacter):
    def __init__(self, info: CharacterInfo, context: CharacterContext):
        super().__init__(info, context)
        w, h = (info.manifest.get("size") or [160, 160])[:2]
        self._size = QSize(max(32, int(w)), max(32, int(h)))
        self._art_faces_left = info.manifest.get("faces", "left") == "left"
        self._animations: Optional[Dict[str, Animation]] = None
        self._overlay: Optional[DesktopOverlay] = None
        self._plan = None
        self._gen = 0                                  # invalidates stale timers

    # ------------------------------------------------------------------ extension hook
    def load_animations(self) -> Dict[str, Animation]:
        """Build animations from the manifest; broken entries are skipped, not fatal."""
        result: Dict[str, Animation] = {}
        for name, spec in (self.info.manifest.get("animations") or {}).items():
            try:
                result[name] = build_animation(spec, self.info.path)
            except AnimationLoadError as exc:
                log.warning("Character '%s': animation '%s' unavailable: %s",
                            self.info.id, name, exc)
        return result

    def get_animation(self, name: str) -> Animation:
        if self._animations is None:
            try:
                self._animations = self.load_animations()
            except Exception:
                log.exception("Character '%s' could not load animations", self.info.id)
                self._animations = {}
        wanted = name
        while name:
            if name in self._animations:
                return self._animations[name]
            name = FALLBACKS.get(name, "")
        return PlaceholderAnimation(wanted)

    # ------------------------------------------------------------------ BaseCharacter
    def show_reminder(self, reminder: Reminder) -> None:
        if self.state != S.HIDDEN:
            self._abort()
        self._reminder = reminder
        overlay = self._ensure_overlay()
        cfg = self.context.config
        self._plan = plan_for_screen(overlay.size(), cfg.application.character_position,
                                     cfg.application.monitor)
        start, end = QPoint(*self._plan.start), QPoint(*self._plan.end)
        self._set_state(S.ENTERING)
        overlay.hide_bubble()
        overlay.set_flip(self._flip_for(end.x() - start.x()))
        overlay.set_animation(self.get_animation("walk"))
        overlay.appear_at(start)
        overlay.slide(start, end, int(cfg.animation.enter_duration * 1000), self._on_entered)

    def react(self, outcome: str) -> None:
        if self._overlay is None or self.state == S.HIDDEN:
            return
        if self.state != S.REMINDER:                    # not asking yet: just leave politely
            log.debug("react(%s) in state %s: leaving", outcome, self.state.value)
            self.hide()
            return
        self._gen += 1
        self._overlay.hide_bubble()
        if outcome == ACTION_COMPLETED:
            self._set_state(S.HAPPY)
            self._overlay.set_animation(self.get_animation("happy"))
        elif outcome == ACTION_SNOOZED:
            self._set_state(S.ANGRY)
            self._overlay.set_animation(self.get_animation("angry"))
        else:
            self._start_exit()
            return
        self._after(int(self.context.config.animation.reaction_duration * 1000), self._start_exit)

    def hide(self, immediate: bool = False) -> None:
        if self.state == S.HIDDEN:
            return
        if immediate:
            reminder = self._reminder
            self._abort()
            if reminder is not None:
                self._reminder = reminder
                self._notify_finished()
        elif self.state != S.EXITING:
            self._gen += 1
            self._start_exit()

    # ------------------------------------------------------------------ choreography
    def _ensure_overlay(self) -> DesktopOverlay:
        if self._overlay is None:
            self._overlay = DesktopOverlay(self._size)
            self._overlay.done_clicked.connect(lambda: self._user_clicked(ACTION_COMPLETED))
            self._overlay.snooze_clicked.connect(lambda: self._user_clicked(ACTION_SNOOZED))
        return self._overlay

    def _on_entered(self) -> None:
        if self.state != S.ENTERING:
            return
        self._set_state(S.IDLE)
        self._overlay.set_flip(False)
        self._overlay.set_animation(self.get_animation("idle"))
        self._after(IDLE_PAUSE_MS, self._present_message)

    def _present_message(self) -> None:
        if self.state != S.IDLE or self._reminder is None:
            return
        self._set_state(S.REMINDER)
        self._overlay.set_animation(self.get_animation("reminder"))
        self._overlay.show_bubble(self._reminder.message,
                                  "Snooze (%s)" % _short_minutes(self._reminder.snooze_minutes))
        auto = self.context.config.reminder.auto_snooze_after_seconds
        if auto > 0:
            self._after(auto * 1000, lambda: self._user_clicked(ACTION_SNOOZED))

    def _user_clicked(self, action: str) -> None:
        if self.state == S.REMINDER:                    # ignores double clicks / late timers
            self._emit_action(action)

    def _start_exit(self) -> None:
        if self._overlay is None or self._plan is None:
            return
        self._set_state(S.EXITING)
        start, end = QPoint(*self._plan.start), QPoint(*self._plan.end)
        self._overlay.hide_bubble()
        self._overlay.set_flip(self._flip_for(start.x() - end.x()))
        self._overlay.set_animation(self.get_animation("walk"))
        self._overlay.slide(self._overlay.pos(), start,
                            int(self.context.config.animation.exit_duration * 1000), self._on_exited)

    def _on_exited(self) -> None:
        if self.state != S.EXITING:
            return
        self._overlay.vanish()
        self._set_state(S.HIDDEN)
        self._notify_finished()

    def _abort(self) -> None:
        self._gen += 1
        if self._overlay is not None:
            self._overlay.vanish()
        self._machine.reset()

    def _after(self, ms: int, fn: Callable[[], None]) -> None:
        gen = self._gen
        QTimer.singleShot(max(0, ms), lambda: fn() if gen == self._gen else None)

    def _flip_for(self, dx: int) -> bool:
        """Mirror the art when moving against the direction it faces."""
        if dx == 0:
            return False
        return (dx > 0) if self._art_faces_left else (dx < 0)


def _short_minutes(m: int) -> str:
    return "%dh" % (m // 60) if m % 60 == 0 and m >= 60 else "%dm" % m
