"""Animation primitives. Anything that can ``render`` itself into a rect is an
animation, so PNG sequences, GIFs, sprite sheets, procedural/vector drawing (and
later skeletal rigs) all plug in the same way."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap


class Animation(ABC):
    @abstractmethod
    def render(self, painter: QPainter, rect: QRectF, t_ms: float) -> None:
        """Draw the frame for time ``t_ms`` (since the animation started) inside ``rect``."""


class FrameAnimation(Animation):
    """Frame-based animation: PNG sequences, GIF/WebP frames and sprite sheets."""

    def __init__(self, frames: List[QPixmap], fps: float = 8.0, loop: bool = True):
        if not frames:
            raise ValueError("an animation needs at least one frame")
        self.frames, self.fps, self.loop = frames, max(0.5, float(fps)), loop

    def frame_index(self, t_ms: float) -> int:
        idx = int(t_ms / 1000.0 * self.fps)
        return idx % len(self.frames) if self.loop else min(idx, len(self.frames) - 1)

    def render(self, painter: QPainter, rect: QRectF, t_ms: float) -> None:
        pix = self.frames[self.frame_index(t_ms)]
        if pix.isNull():
            return
        scale = min(rect.width() / pix.width(), rect.height() / pix.height())
        w, h = pix.width() * scale, pix.height() * scale
        target = QRect(int(rect.x() + (rect.width() - w) / 2), int(rect.y() + rect.height() - h),
                       int(w), int(h))                 # bottom-aligned so feet stay on the ground
        painter.drawPixmap(target, pix)


class ProceduralAnimation(Animation):
    """Draws with QPainter calls: ``draw(painter, rect, t_ms)``. Used by the
    placeholder character; also the hook for vector/skeletal animation later."""

    def __init__(self, draw: Callable[[QPainter, QRectF, float], None]):
        self._draw = draw

    def render(self, painter: QPainter, rect: QRectF, t_ms: float) -> None:
        self._draw(painter, rect, t_ms)


class PlaceholderAnimation(Animation):
    """Last-resort drawing when a character's assets are missing or broken."""

    def __init__(self, label: str):
        self._label = label

    def render(self, painter: QPainter, rect: QRectF, t_ms: float) -> None:
        painter.save()
        painter.setPen(QPen(QColor(120, 120, 120), 2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(240, 240, 240, 200))
        painter.drawRoundedRect(rect.adjusted(8, 8, -8, -8), 12, 12)
        painter.setPen(QColor(90, 90, 90))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter.value,
                         "missing\n" + self._label)
        painter.restore()
