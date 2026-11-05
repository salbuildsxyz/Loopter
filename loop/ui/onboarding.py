"""First-time setup: welcome, choose a display, save your buttons, check them, and finish.

Progress is saved after every step, so an unfinished setup reopens where it stopped.
Nothing in this flow ever clicks: the check step only looks at the screen.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QLinearGradient, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from loop.config import ONBOARDING_STEPS
from loop.ui import icons, motion, theme
from loop.ui.capture_card import CaptureCard
from loop.ui.check_card import CheckCard
from loop.ui.controls import Button, Pressable, paint_focus_ring, surface
from loop.ui.model import TARGETS, Check, Target, ViewState
from loop.ui.screenshot import Display
from loop.ui.widgets import Card, Page, Row, Rows, StateText, Stepper, SuccessMark, column, row, text

STEP_NAMES = ["Welcome", "Display", "Buttons", "Check", "Done"]
assert len(STEP_NAMES) == ONBOARDING_STEPS
WELCOME, DISPLAY, BUTTONS, CHECK, DONE = range(ONBOARDING_STEPS)


class DisplayCard(Pressable):
    """One display, drawn at its real proportions, that can be picked."""

    def __init__(self, display: Display) -> None:
        super().__init__()
        self.display = display
        self.setCheckable(True)
        self.setAccessibleName(
            f"{display.name}, {display.region.width} by {display.region.height}"
            + (", primary" if display.primary else "")
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._on = motion.Tweened(self, 0.0, lambda _v: self.update())
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0, theme.DUR_2))

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return round(16 + self._shape_height(width) + 12 + 20 + 12 + 18 + 16)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(200, self.heightForWidth(200))

    def _shape_height(self, width: int) -> float:
        return (width - 32) * 9 / 16

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        self._begin(painter)
        on, hover = self._on.value, self.hover
        rect = QRectF(self.rect())
        fill = theme.mix(theme.mix(theme.SURFACE, "#151821", hover), "#14161F", on)
        border = theme.mix(theme.mix(theme.BORDER_SUBTLE, theme.BORDER, hover), theme.line(theme.ACCENT), on)
        surface(painter, rect, fill, border, theme.R_LG)
        # The display shape keeps a 16:9 slot and draws the real aspect ratio inside it.
        slot = QRectF(16, 16, rect.width() - 32, self._shape_height(self.width()))
        ratio = self.display.region.width / max(self.display.region.height, 1)
        width = min(slot.width(), slot.height() * ratio)
        height = width / ratio
        shape = QRectF(slot.center().x() - width / 2, slot.center().y() - height / 2, width, height)
        gradient = QLinearGradient(shape.topLeft(), shape.bottomLeft())
        gradient.setColorAt(0, QColor("#171B24"))
        gradient.setColorAt(1, QColor("#11141B"))
        painter.setPen(theme.mix(theme.BORDER, theme.ACCENT, on))
        painter.setBrush(gradient)
        painter.drawRoundedRect(shape.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        painter.setFont(theme.font(16, 600))
        painter.setPen(theme.mix(theme.TEXT_3, theme.ACCENT, on))
        painter.drawText(shape, Qt.AlignmentFlag.AlignCenter, str(self.display.number))
        top = slot.bottom() + 12
        painter.setFont(theme.font(13, 500))
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(
            QRectF(16, top, rect.width() - 52, 20), Qt.AlignmentFlag.AlignVCenter, self.display.name
        )
        if on > 0:
            painter.setOpacity(on)
            size = 16 * (0.8 + 0.2 * on)
            icon = QRectF(rect.width() - 16 - size, top + 10 - size / 2, size, size)
            icons.paint(painter, "check-circle", icon, theme.ACCENT)
            painter.setOpacity(1.0)
        painter.setFont(theme.font(12))
        painter.setPen(QColor(theme.TEXT_2))
        meta = self.display.size + (" · Primary" if self.display.primary else "")
        painter.drawText(QRectF(16, top + 32, rect.width() - 32, 18), Qt.AlignmentFlag.AlignVCenter, meta)
        if self._show_ring():
            paint_focus_ring(painter, rect, theme.R_LG)


class Chip(QWidget):
    """A saved / not saved marker for one button."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(26)
        self.label = ""
        self.done = False
        self._done = motion.Tweened(self, 0.0, lambda _v: self.update())

    def set(self, label: str, done: bool) -> None:
        if (label, done) != (self.label, self.done):
            self.label, self.done = label, done
            self.setAccessibleName(f"{label}: {'saved' if done else 'not saved'}")
            self._done.to(1.0 if done else 0.0, theme.DUR_2)
            self.setFixedWidth(QFontMetrics(theme.font(12)).horizontalAdvance(label) + 20 + 20 + 2)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._done.value
        fill = theme.mix(theme.qcolor(theme.SUCCESS, 0), theme.soft(theme.SUCCESS), t)
        border = theme.mix(theme.BORDER_SUBTLE, theme.line(theme.SUCCESS), t)
        surface(painter, QRectF(self.rect()), fill, border, theme.R_MD)
        color = theme.mix(theme.TEXT_2, theme.SUCCESS, t)
        if self.done:
            icons.paint(painter, "check", QRectF(10, 6, 14, 14), color.name())
        else:
            painter.setPen(QColor(theme.TEXT_3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(12.75, 8.75, 8.5, 8.5))
        painter.setFont(theme.font(12))
        painter.setPen(color)
        painter.drawText(
            QRectF(30, 0, self.width() - 30, self.height()), Qt.AlignmentFlag.AlignVCenter, self.label
        )


class _BrandTile(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(44, 44)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface(painter, QRectF(self.rect()), theme.SURFACE, theme.BORDER, theme.R_XL)
        icons.paint(painter, "loop", QRectF(11, 11, 22, 22), theme.ACCENT, stroke=2)


class Onboarding(QWidget):
    finished = Signal()
    deferred = Signal()
    step_changed = Signal(int)
    display_picked = Signal(int)

    def __init__(self, capture: CaptureCard, check: CheckCard) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        self.capture = capture
        self.check = check
        self.step = -1
        self._displays: list[Display] = []
        self._saved: set[Target] = set()

        layout = column(0)
        self.setLayout(layout)
        top = column(12, (20, 16, 20, 12))
        self.step_label = text("", "label")
        self.later_button = Button("Finish later", self.deferred.emit, "link")
        top.addLayout(row(self.step_label, None, self.later_button))
        self.stepper = Stepper(STEP_NAMES)
        top.addWidget(self.stepper)
        self.top = QWidget()
        self.top.setLayout(top)
        layout.addWidget(self.top)

        self.pages = motion.AnimatedStack()
        self.titles: list[QLabel] = []
        for build in (self._welcome, self._display, self._buttons, self._check, self._done):
            self.pages.addWidget(build())
        layout.addWidget(self.pages, 1)

        self.back_button = Button("Back", lambda: self.show_step(self.step - 1), "ghost", "md", "back")
        self.note = text("", "caption")
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.note.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.skip_button = Button("Skip check", lambda: self.show_step(DONE), "secondary")
        self.next_button = Button("Continue", self._next, "primary")
        self.footer = QWidget()
        self.footer.setLayout(
            row(self.back_button, self.note, self.skip_button, self.next_button, margins=(16, 12, 16, 12))
        )
        layout.addWidget(self.footer)

    # Steps

    def _step_page(self, title: str, lede: str) -> tuple[Page, QVBoxLayout]:
        page = Page(spacing=12)
        page.content.setContentsMargins(20, 16, 20, 24)
        heading = text(title, "title", wrap=True)
        heading.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.titles.append(heading)
        page.content.addWidget(heading)
        lede_label = text(lede, "lede", wrap=True)
        page.content.addWidget(lede_label)
        page.content.addSpacing(4)
        return page, page.content

    def _welcome(self) -> QWidget:
        page = Page(spacing=12)
        page.content.setContentsMargins(28, 16, 28, 24)
        page.content.addStretch(1)
        self.brand = _BrandTile()
        self.welcome_title = text("Welcome to Loopter", "title-lg")
        self.titles.append(self.welcome_title)
        self.welcome_text = text(
            "Loopter watches your game's menus and can press Play for you between matches.", "lede", wrap=True
        )
        points = QWidget()
        points_layout = column(10, (0, 8, 0, 16))
        points.setLayout(points_layout)
        for icon, line in (
            ("eye", "Starts in Watch only — nothing is clicked"),
            ("shield", "Runs on your PC, with an instant emergency stop"),
            ("refresh", "Setup takes about a minute"),
        ):
            mark = QLabel()
            mark.setPixmap(icons.pixmap(icon, theme.TEXT_3, 16))
            point = row(mark, spacing=10)
            point.addWidget(text(line, "body-2", wrap=True), 1)
            points_layout.addLayout(point)
        self.start_button = Button(
            "Get started", lambda: self.show_step(DISPLAY), "primary", "lg", "arrow", icon_right=True
        )
        brand_row = QWidget()
        brand_row.setLayout(row(self.brand, None, margins=(0, 0, 0, 8)))
        self.welcome_items = [brand_row, self.welcome_title, self.welcome_text, points, self.start_button]
        for widget in self.welcome_items[:-1]:
            page.content.addWidget(widget)
        page.content.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignLeft)
        page.content.addStretch(1)
        return page

    def _display(self) -> QWidget:
        page, layout = self._step_page(
            "Which screen is your game on?",
            "We picked your primary display. Choose another one if your game opens there.",
        )
        self.display_grid = QGridLayout()
        self.display_grid.setSpacing(12)
        layout.addLayout(self.display_grid)
        self.no_display = text(
            "No display was found. Check that your monitor is connected.", "help", wrap=True
        )
        layout.addWidget(self.no_display)
        layout.addWidget(text("You can change this later in Settings.", "caption"))
        layout.addStretch(1)
        self.display_cards: list[DisplayCard] = []
        return page

    def _buttons(self) -> QWidget:
        page, layout = self._step_page(
            "Save your buttons", "Loopter needs a picture of your Play button. Play Again is optional."
        )
        self.chips = {t: Chip() for t in TARGETS}
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for chip in self.chips.values():
            chips.addWidget(chip)
        chips.addStretch(1)
        layout.addLayout(chips)
        card = Card()
        card.body.addWidget(self.capture)
        layout.addWidget(card)
        layout.addStretch(1)
        self.buttons_page = page
        return page

    def _check(self) -> QWidget:
        page, layout = self._step_page(
            "Check that it works",
            "Show your game's lobby, then press Check. Loopter looks once and never clicks.",
        )
        card = Card()
        card.body.addWidget(self.check)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _done(self) -> QWidget:
        page = Page(spacing=12)
        page.content.setContentsMargins(20, 24, 20, 24)
        self.success = SuccessMark(48)
        page.content.addWidget(self.success)
        title = text("You're set up", "title")
        title.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.titles.append(title)
        page.content.addWidget(title)
        self.finish_lede = text("Here's what Loopter will use.", "lede", wrap=True)
        page.content.addWidget(self.finish_lede)
        self.summary = Rows()
        self.summary_values: dict[str, QWidget] = {}
        for name in ("Display", "Play / Ready", "Play Again", "Mode"):
            item = Row()
            item.body.addWidget(text(name, "body-2"), 1)
            value: QWidget = text("", "body") if name in ("Display", "Mode") else StateText()
            item.body.addWidget(value)
            self.summary_values[name] = value
            self.summary.add(item)
        page.content.addWidget(self.summary)
        page.content.addStretch(1)
        return page

    # Flow

    def start(self, step: int) -> None:
        self.step = -1
        self.show_step(step, animate=False)

    def show_step(self, step: int, animate: bool = True) -> None:
        step = max(0, min(step, ONBOARDING_STEPS - 1))
        changed = step != self.step
        self.step = step
        if animate:
            self.pages.setCurrentIndex(step)
        else:
            self.pages.jump(step)
        self.stepper.set_step(step)
        if step == WELCOME:
            motion.stagger(self.welcome_items)
            self.start_button.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.titles[step].setFocus(Qt.FocusReason.OtherFocusReason)
        if step == DONE and changed:
            self.success.play()
        self._update_footer()
        if changed:
            self.step_changed.emit(step)

    def _next(self) -> None:
        if self.step >= DONE:
            self.finished.emit()
        else:
            self.show_step(self.step + 1)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if self.step == DISPLAY and event.key() in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            self._move_display(1 if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down) else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _move_display(self, step: int) -> None:
        cards = self.display_cards
        if len(cards) < 2:
            return
        current = next((i for i, c in enumerate(cards) if c.isChecked()), 0)
        card = cards[(current + step) % len(cards)]
        card.setFocus(Qt.FocusReason.TabFocusReason)
        self.display_picked.emit(card.display.number)

    # Rendering

    def set_displays(self, displays: list[Display], current: int) -> None:
        if [d.region for d in displays] != [d.region for d in self._displays]:
            self._displays = displays
            for card in self.display_cards:
                card.setParent(None)
                card.deleteLater()
            self.display_cards = []
            for index, display in enumerate(displays):
                card = DisplayCard(display)
                card.clicked.connect(lambda _c=False, n=display.number: self.display_picked.emit(n))
                self.display_grid.addWidget(card, index // 2, index % 2)
                self.display_cards.append(card)
        for card in self.display_cards:
            card.setChecked(card.display.number == current)
            card.setFocusPolicy(Qt.FocusPolicy.StrongFocus if card.isChecked() else Qt.FocusPolicy.ClickFocus)
        self.no_display.setVisible(not displays)
        summary = next((d for d in displays if d.number == current), None)
        self.summary_values["Display"].setText(f"{summary.name} · {summary.size}" if summary else "—")
        self._update_footer()

    def render(self, view: ViewState) -> None:
        for target, chip in self.chips.items():
            optional = " · optional" if target is Target.AGAIN and target not in view.saved else ""
            chip.set(f"{target.label}{optional}", target in view.saved)
        for target, name in ((Target.PLAY, "Play / Ready"), (Target.AGAIN, "Play Again")):
            value = self.summary_values[name]
            if target is Target.AGAIN and target not in view.saved:
                value.set_state("Add later in Setup", "none")
            else:
                check = view.checks[target]
                value.set_state(check.value, check.tone)
        self.summary_values["Mode"].setText("Watch only")
        checks = [view.checks[t] for t in TARGETS]
        if Check.ADJUST in checks:
            self.finish_lede.setText("One button needs adjustment. You can fix it any time in Setup.")
        elif Check.UNCHECKED in checks:
            self.finish_lede.setText("Buttons marked “Not checked” can be checked any time in Setup.")
        else:
            self.finish_lede.setText("Everything you saved has been checked.")
        self._saved = view.saved
        self._update_footer()

    def _update_footer(self) -> None:
        step = max(self.step, 0)
        saved = self._saved
        self.step_label.setText(f"Step {step + 1} of {ONBOARDING_STEPS} · {STEP_NAMES[step]}")
        self.later_button.setVisible(step != DONE)
        self.footer.setVisible(step != WELCOME)
        self.back_button.setVisible(step != WELCOME)
        self.next_button.setText("Open dashboard" if step == DONE else "Continue")
        checked = self.check.has_run
        self.skip_button.setVisible(step == CHECK and not checked)
        self.next_button.setEnabled(
            not (step == DISPLAY and not self._displays)
            and not (step == BUTTONS and Target.PLAY not in saved)
            and not (step == CHECK and not checked)
        )
        if step == BUTTONS and Target.PLAY not in saved:
            note = "Save Play to continue"
        elif step == BUTTONS and Target.AGAIN not in saved:
            note = "Play Again can wait"
        elif step == CHECK and not checked:
            note = "Check now, or skip it"
        else:
            note = ""
        self.note.setText(note)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG))
        painter.setPen(QColor(theme.BORDER_SUBTLE))
        painter.drawLine(0, 0, self.width(), 0)
        y = self.top.geometry().bottom()
        painter.drawLine(0, y, self.width(), y)
        if self.footer.isVisible():
            y = self.footer.geometry().top()
            painter.drawLine(0, y, self.width(), y)
