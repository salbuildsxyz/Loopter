"""The activity log: timestamped session events, warnings, and errors, with filters."""

from __future__ import annotations

import html
from collections import deque

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from loop.ui import theme
from loop.ui.widgets import IconButton, SegmentedControl, row

MAX_ENTRIES = 2000
LEVEL_COLORS = {"INFO": theme.FG_3, "WARNING": theme.WARN, "ERROR": theme.ERR, "CRITICAL": theme.ERR}
LEVEL_NAMES = {"WARNING": "WARN", "CRITICAL": "FATAL"}
# Messages the session controller logs for clicks and their verification (see describe_event).
ACTION_PREFIXES = ("Clicked ", "Action verified")
FILTERS = {
    "all": lambda level, message: True,
    "action": lambda level, message: message.startswith(ACTION_PREFIXES),
    "warn": lambda level, message: level == "WARNING",
    "error": lambda level, message: level in ("ERROR", "CRITICAL"),
}


class ActivityView(QWidget):
    open_folder_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("View")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 8, 0)
        layout.setSpacing(8)
        self.filters = SegmentedControl(
            [("all", "All", ""), ("action", "Actions", ""), ("warn", "Warnings", ""), ("error", "Errors", "")]
        )
        self.filters.setAccessibleName("Filter log")
        self.filters.set_value("all")
        self.filters.selected.connect(lambda _value: self._render())
        tools = row(
            self.filters,
            None,
            IconButton("copy", "Copy log", self.copy),
            IconButton("trash", "Clear log", self.clear),
            IconButton(
                "folder",
                "Open the folder with settings, templates, and log files",
                self.open_folder_requested,
            ),
            spacing=4,
            margins=(0, 0, 8, 0),
        )
        layout.addLayout(tools)
        self.view = QPlainTextEdit()
        self.view.setObjectName("Log")
        self.view.setReadOnly(True)
        self.view.setAccessibleName("Activity log")
        layout.addWidget(self.view, 1)
        self._entries: deque[tuple[str, str, str]] = deque(maxlen=MAX_ENTRIES)

    @Slot(str, str, str)
    def append(self, timestamp: str, level: str, message: str) -> None:
        self._entries.append((timestamp, level, message))
        if self._shown(level, message):
            self.view.appendHtml(_format(timestamp, level, message))

    def text(self) -> str:
        return "\n".join(
            f"{t}  {LEVEL_NAMES.get(level, level):<5}  {m}"
            for t, level, m in self._entries
            if self._shown(level, m)
        )

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text())

    def clear(self) -> None:
        self._entries.clear()
        self.view.clear()

    def _shown(self, level: str, message: str) -> bool:
        return FILTERS[self.filters.value() or "all"](level, message)

    def _render(self) -> None:
        self.view.clear()
        for entry in self._entries:
            if self._shown(entry[1], entry[2]):
                self.view.appendHtml(_format(*entry))


def _format(timestamp: str, level: str, message: str) -> str:
    color = LEVEL_COLORS.get(level, theme.FG_3)
    name = LEVEL_NAMES.get(level, level).ljust(5).replace(" ", "&nbsp;")
    return (
        f'<span style="color:{theme.FG_3}">{timestamp}</span>&nbsp;&nbsp;'
        f'<span style="color:{color}">{name}</span>&nbsp;&nbsp;'
        f'<span style="color:{theme.FG_1}">{html.escape(message)}</span>'
    )
