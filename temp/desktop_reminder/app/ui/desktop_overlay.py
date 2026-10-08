"""The transparent, borderless, always-on-top window the character lives in."""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter,
                           QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import QPushButton, QWidget

from app.characters.animation import Animation
from app.utils.geometry import MotionPlan, Rect, plan_motion

log = logging.getLogger(__name__)

BUBBLE_W, BUBBLE_H, TAIL_H = 270, 132, 14


def _rect(qr: QRect) -> Rect:
    return Rect(qr.x(), qr.y(), qr.width(), qr.height())


def plan_for_screen(size: QSize, position: str, monitor_mode: str) -> MotionPlan:
    """Pick a monitor (re-evaluated for every reminder, so hot-plugging is fine)."""
    screens = QGuiApplication.screens()
    screen = QGuiApplication.primaryScreen()
    if monitor_mode == "cursor":
        screen = QGuiApplication.screenAt(QCursor.pos()) or screen
    if screen is None:
        raise RuntimeError("no screen available")
    others = [_rect(s.geometry()) for s in screens if s is not screen]
    return plan_motion(_rect(screen.geometry()), _rect(screen.availableGeometry()), others,
                       (size.width(), size.height()), position)


class DesktopOverlay(QWidget):
    done_clicked = Signal()
    snooze_clicked = Signal()

    def __init__(self, character_size: QSize):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus
                 | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        cw, ch = character_size.width(), character_size.height()
        self._width = max(BUBBLE_W, cw)
        self.setFixedSize(self._width, BUBBLE_H + TAIL_H + ch)
        self._char_rect = QRectF((self._width - cw) / 2.0, BUBBLE_H + TAIL_H, cw, ch)

        self._animation: Optional[Animation] = None
        self._t0 = time.monotonic()
        self._flip = False
        self._message = ""
        self._bubble_visible = False
        self._render_failed = False
        self._move_anim: Optional[QPropertyAnimation] = None
        self._move_token = 0

        self._done = self._make_button("Done", "#3FAE6A", self.done_clicked)
        self._snooze = self._make_button("Snooze", "#E39A2D", self.snooze_clicked)
        half = (self._width - 48) // 2
        self._done.setGeometry(16, BUBBLE_H - 46, half, 32)
        self._snooze.setGeometry(32 + half, BUBBLE_H - 46, half, 32)

        self._ticker = QTimer(self)                 # drives frame animation (~30 fps)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self.update)

    # ------------------------------------------------------------------ setup helpers
    def _make_button(self, text: str, colour: str, signal: Signal) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            "QPushButton{background:%s;color:white;border:none;border-radius:8px;"
            "font:bold 10pt 'Segoe UI';}QPushButton:hover{background:#2f2f2f;}" % colour)
        btn.clicked.connect(lambda _checked=False, s=signal: s.emit())
        btn.hide()
        return btn

    # ------------------------------------------------------------------ public API
    def set_animation(self, animation: Animation) -> None:
        self._animation = animation
        self._t0 = time.monotonic()
        self.update()

    def set_flip(self, flip: bool) -> None:
        self._flip = flip

    def show_bubble(self, message: str, snooze_label: str) -> None:
        self._message = message
        self._snooze.setText(snooze_label)
        self._bubble_visible = True
        self._done.show()
        self._snooze.show()
        self.update()

    def hide_bubble(self) -> None:
        self._bubble_visible = False
        self._done.hide()
        self._snooze.hide()
        self.update()

    def appear_at(self, pos: QPoint) -> None:
        self.move(pos)
        self.show()
        self.raise_()                                # re-assert topmost; never activates
        self._ticker.start()

    def vanish(self) -> None:
        self.stop_motion()
        self._ticker.stop()
        self.hide_bubble()
        self.hide()

    def slide(self, start: QPoint, end: QPoint, duration_ms: int,
              on_finished: Optional[Callable[[], None]] = None) -> None:
        self.stop_motion()
        token = self._move_token
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(max(1, duration_ms))
        anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutSine))

        def _done() -> None:
            if token == self._move_token and on_finished:
                on_finished()
        anim.finished.connect(_done)
        self._move_anim = anim
        anim.start()

    def stop_motion(self) -> None:
        self._move_token += 1                        # invalidates pending callbacks
        if self._move_anim is not None:
            self._move_anim.stop()
            self._move_anim = None

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._bubble_visible:
            self._paint_bubble(p)
        if self._animation is not None:
            self._paint_character(p)
        p.end()

    def _paint_character(self, p: QPainter) -> None:
        t_ms = (time.monotonic() - self._t0) * 1000.0
        try:
            p.save()
            if self._flip:
                p.translate(self._char_rect.center().x() * 2.0, 0)
                p.scale(-1.0, 1.0)
            self._animation.render(p, self._char_rect, t_ms)
            p.restore()
        except Exception:
            if not self._render_failed:              # log once, never crash paintEvent
                self._render_failed = True
                log.exception("Character animation failed to render")

    def _paint_bubble(self, p: QPainter) -> None:
        w = self._width
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, w - 2, BUBBLE_H - 2), 16, 16)
        cx = w / 2.0
        tail = QPainterPath()
        tail.addPolygon(QPolygonF([QPointF(cx - 12, BUBBLE_H - 3), QPointF(cx, BUBBLE_H + TAIL_H - 2),
                                   QPointF(cx + 12, BUBBLE_H - 3)]))
        tail.closeSubpath()
        shape = path.united(tail)
        p.setPen(QPen(QColor(60, 60, 70), 2))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawPath(shape)

        text_rect = QRect(16, 10, w - 32, BUBBLE_H - 10 - 54)
        flags = Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value
        size = 15
        while size > 8:                              # shrink long messages to fit
            font = QFont("Segoe UI", size, QFont.Weight.Bold)
            if QFontMetrics(font).boundingRect(text_rect, flags, self._message).height() <= text_rect.height():
                break
            size -= 1
        p.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
        p.setPen(QColor(35, 35, 45))
        p.drawText(text_rect, flags, self._message)
