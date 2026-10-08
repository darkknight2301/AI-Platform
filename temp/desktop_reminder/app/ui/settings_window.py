"""Main window: reminder list, history and application settings."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from app.config import Config
from app.reminders.errors import ReminderError
from app.reminders.reminder import (REPEAT_INTERVAL, REPEAT_ONCE, REPEAT_WEEKLY, Reminder)
from app.reminders.reminder_manager import ReminderManager
from app.ui.reminder_dialog import DAYS, ReminderDialog, SnoozeSelector
from app.utils.geometry import POSITIONS
from app.utils.timefmt import format_12h, format_iso_short

log = logging.getLogger(__name__)
TAB_REMINDERS, TAB_HISTORY, TAB_SETTINGS = 0, 1, 2
ID_ROLE = Qt.ItemDataRole.UserRole


def describe_repeat(r: Reminder) -> str:
    if r.repeat == REPEAT_WEEKLY:
        return "Weekly (%s)" % ", ".join(DAYS[d] for d in r.weekdays)
    if r.repeat == REPEAT_INTERVAL:
        return "Every %d min" % r.interval_minutes
    if r.repeat == REPEAT_ONCE:
        return "Once" + (" (%s)" % r.date if r.date else "")
    return "Daily"


class SettingsWindow(QMainWindow):
    def __init__(self, manager: ReminderManager, characters, config: Config,
                 save_config: Callable[[], None], test_character: Callable[[Optional[str]], None],
                 set_startup: Callable[[bool], bool], startup_enabled: bool):
        super().__init__()
        self._manager, self._characters, self._config = manager, characters, config
        self._save_config, self._test_character, self._set_startup = save_config, test_character, set_startup
        self.setWindowTitle("Desktop Reminder")
        self.resize(820, 520)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_reminders_tab(), "Reminders")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._build_settings_tab(startup_enabled), "Settings")
        self.setCentralWidget(self.tabs)
        self.refresh()

    # ------------------------------------------------------------------ tabs
    def _build_reminders_tab(self) -> QWidget:
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Message", "Time", "Repeat", "Character", "Next due", "Status", "On"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _i: self.edit_selected())

        buttons = QHBoxLayout()
        for label, slot in (("Add Reminder", self.add_reminder), ("Edit", self.edit_selected),
                            ("Delete", self.delete_selected),
                            ("Enable/Disable", self.toggle_selected),
                            ("Test Reminder", self.test_selected)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        return page

    def _build_history_tab(self) -> QWidget:
        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["When", "Reminder", "Outcome"])
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.verticalHeader().setVisible(False)
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        page = QWidget()
        QVBoxLayout(page).addWidget(self.history)
        return page

    def _build_settings_tab(self, startup_enabled: bool) -> QWidget:
        app, rem = self._config.application, self._config.reminder
        self.cb_character = QComboBox()
        for info in self._characters.list():
            self.cb_character.addItem(info.name, info.id)
        self.cb_character.setCurrentIndex(max(0, self.cb_character.findData(app.default_character)))
        self.cb_position = QComboBox()
        for pos in POSITIONS:
            self.cb_position.addItem(pos.replace("_", " ").title(), pos)
        self.cb_position.setCurrentIndex(max(0, self.cb_position.findData(app.character_position)))
        self.cb_monitor = QComboBox()
        self.cb_monitor.addItem("Screen with the mouse", "cursor")
        self.cb_monitor.addItem("Primary screen", "primary")
        self.cb_monitor.setCurrentIndex(max(0, self.cb_monitor.findData(app.monitor)))
        self.snooze = SnoozeSelector()
        self.snooze.set_value(rem.default_snooze_minutes)
        self.chk_sound = QCheckBox("Play sound effects")
        self.chk_sound.setChecked(app.sound_enabled)
        self.chk_startup = QCheckBox("Start Desktop Reminder with Windows")
        self.chk_startup.setChecked(startup_enabled)
        test = QPushButton("Test character animation")
        test.clicked.connect(lambda: self._test_character(self.cb_character.currentData()))

        form = QFormLayout()
        form.addRow("Default character", self.cb_character)
        form.addRow("Position", self.cb_position)
        form.addRow("Show on", self.cb_monitor)
        form.addRow("Default snooze", self.snooze)
        form.addRow("", self.chk_sound)
        form.addRow("", self.chk_startup)
        box = QGroupBox("Application")
        box.setLayout(form)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(box)
        layout.addWidget(test)
        layout.addWidget(QLabel("The default snooze applies to newly created reminders."))
        layout.addStretch(1)

        self.cb_character.currentIndexChanged.connect(self._apply_settings)
        self.cb_position.currentIndexChanged.connect(self._apply_settings)
        self.cb_monitor.currentIndexChanged.connect(self._apply_settings)
        self.chk_sound.toggled.connect(self._apply_settings)
        self.chk_startup.toggled.connect(self._toggle_startup)
        self.snooze._combo.currentIndexChanged.connect(self._apply_settings)
        self.snooze._spin.valueChanged.connect(self._apply_settings)
        return page

    # ------------------------------------------------------------------ settings
    def _apply_settings(self) -> None:
        app = self._config.application
        app.default_character = self.cb_character.currentData() or app.default_character
        app.character_position = self.cb_position.currentData()
        app.monitor = self.cb_monitor.currentData()
        app.sound_enabled = self.chk_sound.isChecked()
        self._config.reminder.default_snooze_minutes = self.snooze.value()
        self._save_config()

    def _toggle_startup(self, checked: bool) -> None:
        if not self._set_startup(checked):
            QMessageBox.warning(self, "Start with Windows",
                                "Could not change the Windows startup setting. See the log for details.")
            self.chk_startup.blockSignals(True)
            self.chk_startup.setChecked(not checked)
            self.chk_startup.blockSignals(False)
            return
        self._config.application.start_with_windows = checked
        self._save_config()

    # ------------------------------------------------------------------ list actions
    def _character_choices(self):
        return [(i.id, i.name) for i in self._characters.list()]

    def _selected_id(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(ID_ROLE) if item else None

    def _need_selection(self) -> Optional[str]:
        rid = self._selected_id()
        if rid is None:
            QMessageBox.information(self, "Desktop Reminder", "Select a reminder first.")
        return rid

    def _run_dialog(self, reminder: Optional[Reminder], apply: Callable[[Reminder], None]) -> None:
        dlg = ReminderDialog(self._character_choices(),
                             self._config.reminder.default_snooze_minutes, reminder, self)
        while dlg.exec():
            try:
                apply(dlg.reminder())
                return
            except ReminderError as exc:                      # keep the dialog open to fix it
                QMessageBox.warning(self, "Cannot save reminder", str(exc))

    @Slot()
    def add_reminder(self) -> None:
        self.show_tab(TAB_REMINDERS)
        self._run_dialog(None, self._manager.add)

    @Slot()
    def edit_selected(self) -> None:
        rid = self._need_selection()
        current = self._manager.get(rid) if rid else None
        if current:
            self._run_dialog(current, self._manager.update)

    @Slot()
    def delete_selected(self) -> None:
        rid = self._need_selection()
        current = self._manager.get(rid) if rid else None
        if current and QMessageBox.question(
                self, "Delete reminder", "Delete '%s'?" % current.message) == QMessageBox.StandardButton.Yes:
            try:
                self._manager.delete(rid)
            except ReminderError as exc:
                QMessageBox.warning(self, "Delete reminder", str(exc))

    @Slot()
    def toggle_selected(self) -> None:
        rid = self._need_selection()
        current = self._manager.get(rid) if rid else None
        if current:
            try:
                self._manager.set_enabled(rid, not current.enabled)
            except ReminderError as exc:
                QMessageBox.warning(self, "Enable/Disable", str(exc))

    @Slot()
    def test_selected(self) -> None:
        rid = self._selected_id()
        current = self._manager.get(rid) if rid else None
        self._test_character(current.character if current else self.cb_character.currentData())

    # ------------------------------------------------------------------ refresh
    def show_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)
        self.show_and_raise()

    def show_and_raise(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    @Slot()
    def refresh(self) -> None:
        selected = self._selected_id()
        names = {i.id: i.name for i in self._characters.list()}
        reminders = sorted(self._manager.list(), key=lambda r: r.time)
        self.table.setRowCount(len(reminders))
        for row, r in enumerate(reminders):
            status = r.status + (" (paused)" if self._manager.paused and r.enabled else "")
            cells = [r.message, format_12h(r.time), describe_repeat(r),
                     names.get(r.character, "Default") if r.character else "Default",
                     format_iso_short(r.next_due or ""), status, "Yes" if r.enabled else "No"]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(ID_ROLE, r.id)
                if not r.enabled:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, col, item)
            if r.id == selected:
                self.table.selectRow(row)
        entries = self._manager.history(200)
        self.history.setRowCount(len(entries))
        for row, e in enumerate(entries):
            for col, text in enumerate((format_iso_short(e.timestamp), e.message,
                                        e.outcome + (" (%s)" % e.detail if e.detail else ""))):
                self.history.setItem(row, col, QTableWidgetItem(text))
