"""System-tray icon and menu."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def build_icon() -> QIcon:
    """Generated at runtime, so the tray works with zero asset files."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(88, 196, 168))
    p.drawEllipse(QRectF(4, 8, 56, 54))
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(QRectF(16, 24, 15, 18))
    p.drawEllipse(QRectF(35, 24, 15, 18))
    p.setBrush(QColor(40, 52, 60))
    p.drawEllipse(QPointF(22, 34), 4, 5)
    p.drawEllipse(QPointF(41, 34), 4, 5)
    p.end()
    return QIcon(pix)


class Tray(QObject):
    def __init__(self, icon: QIcon, on_open: Callable[[], None], on_add: Callable[[], None],
                 on_test: Callable[[], None], on_pause: Callable[[bool], None],
                 on_settings: Callable[[], None], on_exit: Callable[[], None], parent=None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(icon, self)
        self.icon.setToolTip("Desktop Reminder")
        menu = QMenu()
        title = menu.addAction("Desktop Reminder")
        title.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Open Reminders", on_open)
        menu.addAction("Add Reminder", on_add)
        menu.addAction("Test Character", on_test)
        self._pause = QAction("Pause Reminders", menu)
        self._pause.setCheckable(True)
        self._pause.toggled.connect(self._toggled)
        self._on_pause = on_pause
        menu.addAction(self._pause)
        menu.addAction("Settings", on_settings)
        menu.addSeparator()
        menu.addAction("Exit", on_exit)
        self._menu = menu                                   # keep a reference alive
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(
            lambda reason: on_open() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    def _toggled(self, paused: bool) -> None:
        self.icon.setToolTip("Desktop Reminder (paused)" if paused else "Desktop Reminder")
        self._on_pause(paused)

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify_running(self) -> None:
        self.icon.showMessage("Desktop Reminder", "Running in the background. Use the tray icon to open it.",
                              QSystemTrayIcon.MessageIcon.Information, 4000)
