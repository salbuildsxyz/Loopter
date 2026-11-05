"""Loopter's outline icons: one family on a 24 px grid with a 1.5 px round stroke.

The shapes match the approved design's icon set. Icons are rendered at twice their size
so they stay sharp on scaled displays, and cached per color.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

SHAPES = {
    "play": '<path d="M8 5.5v13l10-6.5z"/>',
    "pause": '<path d="M9 6v12M15 6v12"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "eye": (
        '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/>'
        '<circle cx="12" cy="12" r="2.75"/>'
    ),
    "pointer": '<path d="M6 3.5l12 7.5-5.5 1.5L10 18z"/>',
    "check": '<path d="M5.5 12.5l4 4 9-9.5"/>',
    "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.6-4.8"/>',
    "alert": '<path d="M12 4L3 19.5h18z"/><path d="M12 10v4.2M12 16.9h.01"/>',
    "x-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.5l5 5M14.5 9.5l-5 5"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>',
    "camera": '<path d="M4.5 7.5h3.5l1.5-2.5h5L16 7.5h3.5v11h-15z"/><circle cx="12" cy="12.75" r="3.25"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5L20 20"/>',
    "chevron": '<path d="M9.5 6l6 6-6 6"/>',
    "down": '<path d="M6 9.5l6 6 6-6"/>',
    "back": '<path d="M14.5 5.5L8 12l6.5 6.5"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
    "keyboard": (
        '<rect x="2.5" y="6.5" width="19" height="11" rx="2"/>'
        '<path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M8 14h8"/>'
    ),
    "shield": '<path d="M12 3.5l7 2.5v5.5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5v-4h-11v11h4"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5"/>',
    "folder": '<path d="M3.5 6.5v12h17v-10h-9l-2-2z"/>',
    "upload": '<path d="M12 15V4.5M7.5 9L12 4.5 16.5 9M4.5 15.5v4h15v-4"/>',
    "download": '<path d="M12 4.5V15M7.5 10.5L12 15l4.5-4.5M4.5 15.5v4h15v-4"/>',
    "scan": (
        '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 '
        '1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M4 12h16"/>'
    ),
    "activity": '<path d="M3 12h4l2.5-6 5 12 2.5-6h4"/>',
    "loop": (
        '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/>'
        '<circle cx="19.5" cy="12" r="1.6" fill="{color}" stroke="none"/>'
    ),
}

_SCALE = 2


@cache
def pixmap(name: str, color: str, size: int = 16, stroke: float = 1.5) -> QPixmap:
    shape = SHAPES[name].replace("{color}", color)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{shape}</svg>'
    )
    result = QPixmap(size * _SCALE, size * _SCALE)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(result.rect()))
    painter.end()
    result.setDevicePixelRatio(_SCALE)
    return result


def paint(painter: QPainter, name: str, rect: QRectF, color: str, stroke: float = 1.5) -> None:
    """Draws an icon into `rect` (logical pixels)."""
    size = round(max(rect.width(), rect.height()))
    painter.drawPixmap(rect.toRect(), pixmap(name, color, size, stroke))
