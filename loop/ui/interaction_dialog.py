"""The confirmation shown every time Live Interaction is selected."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from loop.input_guard import USER_IDLE_S
from loop.ui import icons, theme
from loop.ui.widgets import Notice, button, label, row

RISK_TEXT = (
    "Automating an online game may break its terms of service and can lead to account "
    "restrictions. LOOP does not hide its input and is not undetectable. Only use this "
    "where automation is allowed, and stay at your computer."
)


class InteractionDialog(QDialog):
    def __init__(self, parent: QWidget | None, hotkey: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Live Interaction")
        self.setModal(True)
        self.setFixedWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        mark = QLabel()
        mark.setFixedSize(20, 20)
        mark.setPixmap(icons.pixmap("alert", theme.WARN, 18))
        layout.addLayout(row(mark, label("Turn on Live Interaction?", "Title"), None))
        layout.addWidget(
            label("LOOP will press Play and Play Again with real mouse clicks for this session.", wrap=True)
        )
        guards = QVBoxLayout()
        guards.setSpacing(6)
        for name, text in (
            ("pointer", "Clicks only the foreground window, never LOOP itself."),
            ("pause", f"Waits until you have not touched the mouse or keyboard for {USER_IDLE_S:g} s."),
            ("keyboard", f"{hotkey} stops everything instantly."),
            ("refresh", "Must be confirmed again after every restart or emergency stop."),
        ):
            glyph = QLabel()
            glyph.setFixedSize(16, 16)
            glyph.setPixmap(icons.pixmap(name, theme.FG_3, 14))
            line = QHBoxLayout()
            line.setSpacing(8)
            line.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(label(text, "Secondary", wrap=True), 1)
            guards.addLayout(line)
        layout.addLayout(guards)
        layout.addWidget(Notice(RISK_TEXT, "warn"))

        self.accept_risk = QCheckBox("I understand and accept the risk")
        layout.addWidget(self.accept_risk)
        cancel = button("Cancel", self.reject)
        self.confirm = button("Turn on", self.accept, "warn")
        self.confirm.setEnabled(False)
        self.accept_risk.toggled.connect(self.confirm.setEnabled)
        cancel.setDefault(True)
        layout.addLayout(row(None, cancel, self.confirm))


def confirm_live_interaction(parent: QWidget, hotkey: str) -> bool:
    return InteractionDialog(parent, hotkey).exec() == QDialog.DialogCode.Accepted
