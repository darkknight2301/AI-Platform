"""Pebble: a placeholder character drawn entirely with QPainter shapes.

It exists so the whole flow works without any art files, and shows the code-based
route for a custom character: subclass SpriteCharacter, override load_animations.
Replace it (or add siblings) with your own, legally owned artwork.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from app.characters.animation import ProceduralAnimation
from app.characters.sprite_character import SpriteCharacter

BODY = QColor(88, 196, 168)
BODY_ANGRY = QColor(232, 96, 84)
DARK = QColor(40, 52, 60)
WHITE = QColor(255, 255, 255)


def _mix(a: QColor, b: QColor, f: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * f), int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


def draw_pebble(p: QPainter, rect: QRectF, t_ms: float, mood: str) -> None:
    t = t_ms / 1000.0
    swing = dx = dy = 0.0
    if mood == "walk":
        swing, dy = math.sin(t * 10), -abs(math.sin(t * 10)) * 4
    elif mood == "idle":
        dy = math.sin(t * 2.5) * 2
    elif mood == "reminder":
        dy = -abs(math.sin(t * 4)) * 5
    elif mood == "happy":
        dy = -abs(math.sin(t * 8)) * 22
    elif mood == "angry":
        dx = math.sin(t * 45) * 4
    body = _mix(BODY, BODY_ANGRY, 1.0 if mood == "angry" else 0.0)

    p.save()
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 160.0, rect.height() / 160.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 55))                              # ground shadow
    p.drawEllipse(QRectF(40, 146, 80, 10))
    p.translate(dx, dy)

    p.setBrush(DARK)                                             # legs
    p.drawRoundedRect(QRectF(58 + swing * 7, 120, 16, 26), 6, 6)
    p.drawRoundedRect(QRectF(86 - swing * 7, 120, 16, 26), 6, 6)

    p.setBrush(body)                                             # arms
    for shoulder, sign in ((QPointF(38, 84), 1), (QPointF(122, 84), -1)):
        if mood == "happy":
            angle = sign * (150 + math.sin(t * 8) * 12)
        elif mood == "angry":
            angle = sign * 12
        elif mood == "walk":
            angle = sign * swing * 28
        else:
            angle = sign * 6
        p.save()
        p.translate(shoulder)
        p.rotate(angle)
        p.drawRoundedRect(QRectF(-8, -4, 16, 38), 8, 8)
        p.restore()

    p.setBrush(body)                                             # body
    p.drawEllipse(QRectF(35, 40, 90, 92))
    p.setBrush(QColor(70, 160, 90))                              # leaf on top
    p.save()
    p.translate(80, 42)
    p.rotate(-25)
    p.drawEllipse(QRectF(-6, -28, 12, 30))
    p.restore()

    if mood == "happy":                                          # ^ ^ eyes + cheeks
        p.setPen(QPen(DARK, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(52, 64, 24, 20), 0, 180 * 16)
        p.drawArc(QRectF(84, 64, 24, 20), 0, 180 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 150, 160, 170))
        p.drawEllipse(QRectF(44, 82, 14, 9))
        p.drawEllipse(QRectF(102, 82, 14, 9))
    else:
        look = -4 if mood == "walk" else 0                       # looks where it is walking
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(WHITE)
        p.drawEllipse(QRectF(50, 60, 26, 30))
        p.drawEllipse(QRectF(84, 60, 26, 30))
        p.setBrush(DARK)
        p.drawEllipse(QRectF(58 + look, 70, 11, 14))
        p.drawEllipse(QRectF(91 + look, 70, 11, 14))
        if mood == "angry":
            p.setPen(QPen(DARK, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(48, 54), QPointF(78, 66))
            p.drawLine(QPointF(112, 54), QPointF(82, 66))

    p.setBrush(Qt.BrushStyle.NoBrush)                            # mouth
    p.setPen(QPen(DARK, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if mood == "happy":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(DARK)
        p.drawChord(QRectF(62, 90, 36, 26), 180 * 16, 180 * 16)
    elif mood == "angry":
        p.drawArc(QRectF(66, 102, 28, 14), 20 * 16, 140 * 16)    # frown
    elif mood == "reminder":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(DARK)
        p.drawEllipse(QRectF(72, 98, 16, 6 + abs(math.sin(t * 9)) * 9))   # talking
    else:
        p.drawArc(QRectF(66, 94, 28, 14), 200 * 16, 140 * 16)    # smile
    p.restore()


class DefaultCharacter(SpriteCharacter):
    def load_animations(self):
        def make(mood):
            return ProceduralAnimation(lambda p, r, t, m=mood: draw_pebble(p, r, t, m))
        return {name: make(name) for name in ("walk", "idle", "reminder", "happy", "angry")}


def create_character(info, context):
    return DefaultCharacter(info, context)
