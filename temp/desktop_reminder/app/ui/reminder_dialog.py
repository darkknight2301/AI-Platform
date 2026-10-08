"""Add / edit reminder dialog."""
from __future__ import annotations

import copy
from datetime import date
from typing import List, Optional, Tuple

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
                               QTimeEdit, QVBoxLayout, QWidget)

from app.reminders.reminder import (REPEAT_DAILY, REPEAT_INTERVAL, REPEAT_ONCE, REPEAT_WEEKLY,
                                    Reminder)

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SNOOZE_PRESETS = (5, 10, 15, 30, 60)


class SnoozeSelector(QWidget):
    """5 / 10 / 15 / 30 / 60 minutes or a custom value."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._combo = QComboBox()
        for m in SNOOZE_PRESETS:
            self._combo.addItem("1 hour" if m == 60 else "%d minutes" % m, m)
        self._combo.addItem("Custom...", -1)
        self._spin = QSpinBox()
        self._spin.setRange(1, 1440)
        self._spin.setSuffix(" min")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._combo)
        layout.addWidget(self._spin)
        self._combo.currentIndexChanged.connect(self._sync)
        self.set_value(10)

    def _sync(self) -> None:
        self._spin.setVisible(self._combo.currentData() == -1)

    def value(self) -> int:
        data = self._combo.currentData()
        return self._spin.value() if data == -1 else int(data)

    def set_value(self, minutes: int) -> None:
        idx = self._combo.findData(int(minutes))
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        else:
            self._combo.setCurrentIndex(self._combo.findData(-1))
            self._spin.setValue(int(minutes))
        self._sync()


class ReminderDialog(QDialog):
    def __init__(self, characters: List[Tuple[str, str]], default_snooze: int,
                 reminder: Optional[Reminder] = None, parent=None):
        super().__init__(parent)
        self._original = reminder
        self.setWindowTitle("Edit reminder" if reminder else "Add reminder")
        self.setMinimumWidth(420)

        self.message = QLineEdit()
        self.message.setPlaceholderText("e.g. Drink Water \U0001F4A7")
        self.message.setMaxLength(200)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("hh:mm AP")
        self.repeat = QComboBox()
        for label, mode in (("Once", REPEAT_ONCE), ("Daily", REPEAT_DAILY),
                            ("Weekly", REPEAT_WEEKLY), ("Custom interval", REPEAT_INTERVAL)):
            self.repeat.addItem(label, mode)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.days = [QCheckBox(d) for d in DAYS]
        days_row = QHBoxLayout()
        for cb in self.days:
            days_row.addWidget(cb)
        self.days_widget = QWidget()
        self.days_widget.setLayout(days_row)
        days_row.setContentsMargins(0, 0, 0, 0)
        self.interval = QSpinBox()
        self.interval.setRange(1, 10080)
        self.interval.setValue(60)
        self.interval.setSuffix(" min")
        self.snooze = SnoozeSelector()
        self.snooze.set_value(default_snooze)
        self.sound = QCheckBox("Play sounds")
        self.sound.setChecked(True)
        self.character = QComboBox()
        self.character.addItem("(Default character)", "")
        for cid, name in characters:
            self.character.addItem(name, cid)
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)

        form = QFormLayout()
        form.addRow("Message", self.message)
        form.addRow("Time", self.time)
        form.addRow("Repeat", self.repeat)
        self._date_label = QLabel("Date")
        form.addRow(self._date_label, self.date)
        self._days_label = QLabel("Days")
        form.addRow(self._days_label, self.days_widget)
        self._interval_label = QLabel("Every")
        form.addRow(self._interval_label, self.interval)
        form.addRow("Snooze", self.snooze)
        form.addRow("Character", self.character)
        form.addRow("", self.sound)
        form.addRow("", self.enabled)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(buttons)

        self.repeat.currentIndexChanged.connect(self._update_visibility)
        self._load(reminder)
        self._update_visibility()

    def _load(self, r: Optional[Reminder]) -> None:
        if r is None:
            self.time.setTime(QTime.currentTime().addSecs(300))
            self.repeat.setCurrentIndex(self.repeat.findData(REPEAT_DAILY))
            self.days[date.today().weekday()].setChecked(True)
            return
        self.message.setText(r.message)
        h, m = (int(x) for x in r.time.split(":"))
        self.time.setTime(QTime(h, m))
        self.repeat.setCurrentIndex(self.repeat.findData(r.repeat))
        if r.date:
            self.date.setDate(QDate.fromString(r.date, "yyyy-MM-dd"))
        for d in r.weekdays:
            self.days[d].setChecked(True)
        self.interval.setValue(r.interval_minutes)
        self.snooze.set_value(r.snooze_minutes)
        self.sound.setChecked(r.sound_enabled)
        self.enabled.setChecked(r.enabled)
        idx = self.character.findData(r.character)
        self.character.setCurrentIndex(max(0, idx))

    def _update_visibility(self) -> None:
        mode = self.repeat.currentData()
        for w, show in ((self.date, mode == REPEAT_ONCE), (self._date_label, mode == REPEAT_ONCE),
                        (self.days_widget, mode == REPEAT_WEEKLY),
                        (self._days_label, mode == REPEAT_WEEKLY),
                        (self.interval, mode == REPEAT_INTERVAL),
                        (self._interval_label, mode == REPEAT_INTERVAL)):
            w.setVisible(show)

    def reminder(self) -> Reminder:
        """Reminder built from the form (not yet validated by the engine)."""
        r = copy.deepcopy(self._original) if self._original else Reminder(message="", time="00:00")
        mode = self.repeat.currentData()
        r.message = self.message.text()
        r.time = self.time.time().toString("HH:mm")
        r.repeat = mode
        r.date = self.date.date().toString("yyyy-MM-dd") if mode == REPEAT_ONCE else None
        r.weekdays = [i for i, cb in enumerate(self.days) if cb.isChecked()] if mode == REPEAT_WEEKLY else []
        r.interval_minutes = self.interval.value()
        r.snooze_minutes = self.snooze.value()
        r.sound_enabled = self.sound.isChecked()
        r.character = self.character.currentData() or ""
        r.enabled = self.enabled.isChecked()
        return r
