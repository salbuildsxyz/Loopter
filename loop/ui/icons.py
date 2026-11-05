"""LOOP's outline icons: a 24 px grid with a 1.5 px stroke, drawn at 14–16 px."""

from __future__ import annotations

import math
from functools import cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from loop.ui import theme


def _gear() -> str:
    points = []
    for i in range(32):
        angle = math.radians(i * 360 / 32)
        radius = 9.0 if i % 4 in (1, 2) else 7.2
        points.append(f"{12 + radius * math.cos(angle):.2f} {12 + radius * math.sin(angle):.2f}")
    return f'<path d="M{"L".join(points)}z"/><circle cx="12" cy="12" r="2.8"/>'


_SHAPES = {
    "play": '<path d="M7.5 5v14l11-7z"/>',
    "idle": '<circle cx="12" cy="12" r="7.5"/>',
    "pause": '<path d="M8.5 5.5v13M15.5 5.5v13"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
    "alert": '<path d="M12 3.8L2.8 19.8h18.4z"/><path d="M12 10v4.2M12 16.9h.01"/>',
    "gear": _gear(),
    "eye": (
        '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/>'
        '<circle cx="12" cy="12" r="2.75"/>'
    ),
    "demo": '<rect x="3.5" y="4.5" width="17" height="12" rx="1.5"/><path d="M8.5 20h7M12 16.5V20"/>',
    "back": '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
    "chevron": '<path d="M9.5 6l6 6-6 6"/>',
    "down": '<path d="M6 9.5l6 6 6-6"/>',
    "upload": '<path d="M12 15V4.5M7.5 9L12 4.5 16.5 9M4.5 15.5v4h15v-4"/>',
    "download": '<path d="M12 4.5V15M7.5 10.5L12 15l4.5-4.5M4.5 15.5v4h15v-4"/>',
    "target": (
        '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>'
    ),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="1.5"/><path d="M15.5 8.5v-4h-11v11h4"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5M10 11v5M14 11v5"/>',
    "folder": '<path d="M3.5 6.5v12h17v-10h-9l-2-2z"/>',
    "pointer": '<path d="M6 3.5l12 7.5-5.5 1.5L10 18z"/>',
    "keyboard": (
        '<rect x="2.5" y="6.5" width="19" height="11" rx="1.5"/>'
        '<path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M8 14h8"/>'
    ),
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.6-4.8"/>',
    "camera": ('<path d="M4.5 7.5h3.5l1.5-2.5h5L16 7.5h3.5v11h-15z"/><circle cx="12" cy="12.75" r="3.25"/>'),
    "search": '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5L20 20"/>',
}

_BRAND = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    f'<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" fill="none" stroke="{theme.ACCENT}" '
    'stroke-width="2.4" stroke-linecap="round"/>'
    f'<circle cx="19.5" cy="12" r="2.2" fill="{theme.FG_1}"/></svg>'
)

# Icons are drawn at twice their size so they stay sharp on scaled displays.
_SCALE = 2


def _render(svg: str, size: int) -> QPixmap:
    pixmap = QPixmap(size * _SCALE, size * _SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(pixmap.rect()))
    painter.end()
    pixmap.setDevicePixelRatio(_SCALE)
    return pixmap


@cache
def pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{_SHAPES[name]}</svg>'
    )
    return _render(svg, size)


def icon(name: str, color: str = theme.FG_2, checked: str | None = None, size: int = 16) -> QIcon:
    """An icon in `color`, dimmed when disabled, and in `checked` when its button is checked."""
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, checked or color, size), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, theme.LINE_2, size), QIcon.Mode.Disabled, QIcon.State.Off)
    result.addPixmap(pixmap(name, theme.FG_3, size), QIcon.Mode.Disabled, QIcon.State.On)
    return result


@cache
def brand(size: int = 20) -> QPixmap:
    return _render(_BRAND, size)
