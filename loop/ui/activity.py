"""Activity: every log line as a readable timeline entry, newest first."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget

from loop.ui import icons, motion, theme
from loop.ui.controls import Button, IconButton, Pressable, SegmentedControl, surface
from loop.ui.model import FILTERS, Entry, make_entry
from loop.ui.widgets import EmptyState, Page, column, row, text

MAX_ENTRIES = 500
KIND_ICONS = {
    "detect": ("eye", theme.TEXT_2, theme.ELEVATED),
    "click": ("pointer", theme.ACCENT, theme.ELEVATED),
    "ok": ("check", theme.SUCCESS, theme.ELEVATED),
    "warn": ("alert", theme.WARNING, theme.soft(theme.WARNING)),
    "error": ("x-circle", theme.DANGER, theme.soft(theme.DANGER)),
    "info": ("info", theme.TEXT_2, theme.ELEVATED),
}


class _EntryHead(Pressable):
    """Time · icon · title · chevron, on one 40 px row."""

    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry
        self.setCheckable(True)
        self.setMinimumHeight(theme.H_ROW)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{entry.time} {entry.title}")
        self.turn = motion.Tweened(self, 0.0, lambda _v: self.update())

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if self.hover > 0:
            painter.fillRect(rect, theme.qcolor(theme.ELEVATED, self.hover))
        cy = rect.center().y()
        painter.setFont(theme.font(11, mono=True))
        painter.setPen(QColor(theme.TEXT_3))
        painter.drawText(QRectF(12, 0, 56, rect.height()), Qt.AlignmentFlag.AlignVCenter, self.entry.time)
        icon, color, fill = KIND_ICONS[self.entry.kind]
        tile = QRectF(78, cy - 10, 20, 20)
        surface(painter, tile, fill, None, 5)
        icons.paint(painter, icon, tile.adjusted(3, 3, -3, -3), color)
        painter.setFont(theme.font(13))
        painter.setPen(QColor(theme.TEXT))
        title_width = int(rect.width() - 108 - 10 - 14 - 12)
        title = painter.fontMetrics().elidedText(self.entry.title, Qt.TextElideMode.ElideRight, title_width)
        painter.drawText(QRectF(108, 0, title_width, rect.height()), Qt.AlignmentFlag.AlignVCenter, title)
        painter.save()
        painter.translate(rect.width() - 12 - 7, cy)
        painter.rotate(90 * self.turn.value)
        icons.paint(painter, "chevron", QRectF(-7, -7, 14, 14), theme.TEXT_3)
        painter.restore()
        if self._show_ring():
            painter.setPen(theme.line(theme.ACCENT))
            painter.drawRect(rect.adjusted(1, 1, -2, -2))


class TimelineItem(QWidget):
    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry
        layout = column(0)
        self.setLayout(layout)
        self.head = _EntryHead(entry)
        self.head.toggled.connect(self._toggle)
        layout.addWidget(self.head)
        self.detail = text(entry.message, "mono", wrap=True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setContentsMargins(98, 0, 12, 10)
        self.detail.setMaximumHeight(0)
        self.detail.hide()
        layout.addWidget(self.detail)
        self._open = motion.Tweened(self, 0.0, self._grow)

    @property
    def expanded(self) -> bool:
        return self.head.isChecked()

    def _toggle(self, open_: bool) -> None:
        self.head.turn.to(1.0 if open_ else 0.0, theme.DUR_2, theme.EASE_MOVE)
        if open_:
            self.detail.show()
        self._open.to(1.0 if open_ else 0.0, theme.DUR_2, theme.EASE_MOVE)

    def _grow(self, t: float) -> None:
        full = self.detail.heightForWidth(max(self.detail.width(), 1))
        self.detail.setMaximumHeight(16777215 if t >= 1.0 else round(max(full, 0) * t))
        if t <= 0.0 and not self.expanded:
            self.detail.hide()


class Timeline(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.body = column(0, (1, 1, 1, 1))
        self.setLayout(self.body)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER_SUBTLE, theme.R_LG)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        shown = [self.body.itemAt(i).widget() for i in range(self.body.count())]
        shown = [w for w in shown if w is not None and not w.isHidden()]
        for widget in shown[1:]:
            painter.drawLine(1, widget.y(), self.width() - 2, widget.y())


class ActivityPage(Page):
    home_requested = Signal()
    open_folder_requested = Signal()
    message = Signal(str, str)

    def __init__(self) -> None:
        super().__init__(spacing=20)
        self.copy_button = IconButton("copy", "Copy activity", self.copy)
        self.clear_button = IconButton("trash", "Clear activity", self.clear)
        self.folder_button = IconButton("folder", "Open log folder", self.open_folder_requested.emit)
        head = row(
            text("Activity", "title"),
            8,
            None,
            self.copy_button,
            self.clear_button,
            self.folder_button,
            spacing=4,
        )
        self.content.addLayout(head)
        self.filters = SegmentedControl(
            [("all", "All", ""), ("click", "Clicks", ""), ("warn", "Warnings", ""), ("error", "Errors", "")],
            size="sm",
            fit=True,
        )
        self.filters.setAccessibleName("Show")
        self.filters.set_value("all", animate=False)
        self.filters.picked.connect(self.set_filter)
        self.content.addWidget(self.filters, 0, Qt.AlignmentFlag.AlignLeft)
        self.timeline = Timeline()
        self.content.addWidget(self.timeline)
        self.empty_action = Button("Go to Home", self._empty_action, "secondary", "sm")
        self.empty = EmptyState("activity", self.empty_action)
        self.content.addWidget(self.empty)
        self.content.addStretch(1)
        self.items: list[TimelineItem] = []
        self._refresh()

    @property
    def filter(self) -> str:
        return self.filters.value()

    def append(self, time: str, level: str, message: str) -> Entry:
        entry = make_entry(time, level, message)
        item = TimelineItem(entry)
        self.items.insert(0, item)
        self.timeline.body.insertWidget(0, item)
        while len(self.items) > MAX_ENTRIES:
            old = self.items.pop()
            old.setParent(None)
            old.deleteLater()
        item.setVisible(FILTERS[self.filter](entry))
        self._refresh()
        if item.isVisible() and self.isVisible():
            motion.rise_in(item, theme.DUR_3, 4)
        return entry

    def set_filter(self, value: str) -> None:
        self.filters.set_value(value)
        for item in self.items:
            item.setVisible(FILTERS[value](item.entry))
        self._refresh()

    def visible_entries(self) -> list[Entry]:
        return [i.entry for i in self.items if not i.isHidden()]

    def copy(self) -> None:
        entries = self.visible_entries()
        lines = [f"{e.time}  {e.message}" for e in reversed(entries)]
        QGuiApplication.clipboard().setText("\n".join(lines))
        if entries:
            self.message.emit(f"Copied {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}", "ok")
        else:
            self.message.emit("Nothing to copy", "info")

    def clear(self) -> None:
        if not self.items:
            self.message.emit("Activity is already empty", "info")
            return
        for item in self.items:
            item.setParent(None)
            item.deleteLater()
        self.items = []
        self._refresh()
        self.message.emit("Activity cleared", "ok")

    def _empty_action(self) -> None:
        if self.items:
            self.set_filter("all")
        else:
            self.home_requested.emit()

    def _refresh(self) -> None:
        shown = any(not i.isHidden() for i in self.items)
        self.timeline.setVisible(shown)
        self.empty.setVisible(not shown)
        if not shown:
            filtered = bool(self.items)
            self.empty.title.setText("Nothing matches this filter" if filtered else "No activity yet")
            self.empty.body.setText(
                "Loopter hasn't logged anything of this kind."
                if filtered
                else "Start a session and Loopter lists what it recognizes and clicks here."
            )
            self.empty_action.setText("Show everything" if filtered else "Go to Home")
        self.timeline.update()
