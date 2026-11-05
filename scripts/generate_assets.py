"""Regenerates the bundled demo fixtures and app icon. All artwork is drawn here from scratch.

The screens mirror the states of a typical battle royale loop (lobby, matchmaking,
loading, match, results, finding the next match) with generic, original artwork.
Decoys with similar colors or text sit beside the real buttons so tests can prove
LOOP never confuses them.

Usage: python scripts/generate_assets.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "loop" / "assets"
W, H = 960, 540

BG = QColor("#15161B")
PANEL = QColor("#1C1E24")
LINE = QColor("#2A2D35")
TEXT = QColor("#ECECF1")
MUTED = QColor("#8B8D98")
ACCENT = QColor("#A78BFA")
INK = QColor("#14151A")
YELLOW = QColor("#F4EA3A")
CREAM = QColor("#FBF3D9")
LAVENDER = QColor("#D9D3F7")
TAB = QColor("#D9DAE0")
LOBBY_PANEL = QColor("#2B2721")
RESULTS_BG = QColor("#4634B8")
PROMO_BG = QColor("#5B6FD8")
SPECTATE_BG = QColor("#5B9BD0")
SPECTATE_BAR = QColor("#1A2140")

# Kept in sync with BUTTON_AREAS in loop/demo/scenario.py: decoys stay outside these areas.
LOBBY_BUTTON_AREA = (52, 404, 256, 96)


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal, italic: bool = False) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(round(size))
    f.setWeight(weight)
    f.setItalic(italic)
    return f


def canvas(width: int, height: int, fill: QColor) -> tuple[QImage, QPainter]:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(fill)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    return image, painter


def save(image: QImage, painter: QPainter, path: Path) -> None:
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path)):
        raise SystemExit(f"Could not write {path}")
    print("wrote", path.relative_to(ROOT))


def button(
    width: int,
    height: int,
    text: str,
    fill: QColor | QLinearGradient,
    background: QColor,
    outline: QColor | None = None,
    size: float = 0.42,
) -> QImage:
    image, p = canvas(width, height, background)
    p.setPen(QPen(outline, 3) if outline else Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawRoundedRect(QRectF(1.5, 1.5, width - 3, height - 3), 8, 8)
    p.setPen(INK)
    p.setFont(font(height * size, QFont.Weight.Black))
    p.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return image


def cosmetic_button(width: int, height: int, background: QColor) -> QImage:
    """A shimmering button with a yellow rim: similar colors to Play, but not a Play button."""
    fill = QLinearGradient(0, 0, width, 0)
    fill.setColorAt(0.0, QColor("#F6E7A8"))
    fill.setColorAt(0.6, QColor("#F3D2EC"))
    fill.setColorAt(1.0, QColor("#D9B8F2"))
    return button(width, height, "EQUIP ITEM", fill, background, outline=QColor("#F2C230"), size=0.4)


def text_badge(
    width: int,
    height: int,
    text: str,
    background: QColor,
    size: float,
    weight: QFont.Weight = QFont.Weight.Normal,
    italic: bool = False,
) -> QImage:
    image, p = canvas(width, height, background)
    p.setPen(TEXT)
    p.setFont(font(size, weight, italic))
    p.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.end()
    return image


def loading_badge() -> QImage:
    image, p = canvas(220, 56, BG)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PANEL)
    p.drawRoundedRect(QRectF(0, 0, 220, 56), 12, 12)
    p.setPen(QPen(ACCENT, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(18, 14, 28, 28), 90 * 16, 270 * 16)
    p.setPen(TEXT)
    p.setFont(font(17, QFont.Weight.DemiBold))
    p.drawText(QRectF(60, 0, 150, 56), Qt.AlignmentFlag.AlignVCenter, "LOADING")
    p.end()
    return image


def templates() -> dict[str, QImage]:
    images = {
        "play": button(236, 60, "PLAY", YELLOW, LOBBY_PANEL),
        "ready": button(236, 60, "READY", YELLOW, LOBBY_PANEL),
        "play_again": button(300, 64, "PLAY AGAIN", YELLOW, RESULTS_BG),
        "matchmaking": text_badge(150, 26, "Finding server", LOBBY_PANEL, 17),
        "finding": text_badge(
            380, 44, "FINDING NEXT MATCH", SPECTATE_BG, 30, QFont.Weight.Black, italic=True
        ),
        "loading": loading_badge(),
    }
    out = ASSETS / "demo" / "templates"
    out.mkdir(parents=True, exist_ok=True)
    for name, image in images.items():
        if not image.save(str(out / f"{name}.png")):
            raise SystemExit(f"Could not write {name}.png")
        print("wrote", (out / f"{name}.png").relative_to(ROOT))
    return images


def footer(p: QPainter, color: QColor = MUTED) -> None:
    p.setPen(color)
    p.setFont(font(12))
    p.drawText(40, H - 14, "LOOP demo environment · local fixtures only")


def lobby(sprites: dict[str, QImage], matchmaking: bool) -> tuple[QImage, QPainter]:
    image, p = canvas(W, H, BG)
    # Navigation tabs, including a small Play tab that must never be taken for the Play button.
    p.drawImage(40, 16, button(70, 30, "PLAY", TAB, BG, size=0.5))
    p.setPen(TEXT)
    p.setFont(font(15, QFont.Weight.Bold))
    for i, name in enumerate(("SHOP", "LOCKER", "QUESTS", "CAREER")):
        p.drawText(132 + i * 92, 37, name)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(LOBBY_PANEL)
    p.drawRoundedRect(QRectF(40, 196, 280, 316), 10, 10)
    p.setPen(TEXT)
    p.setFont(font(38, QFont.Weight.Black))
    p.drawText(56, 246, "SQUADS")
    mode = QColor("#8C8370") if matchmaking else QColor("#BDB08A")
    p.drawImage(52, 300, button(256, 42, "Build  ·  Solo", mode, LOBBY_PANEL, size=0.45))
    p.drawImage(52, 352, cosmetic_button(256, 42, LOBBY_PANEL))
    if matchmaking:
        p.drawImage(56, 258, sprites["matchmaking"])
        p.setPen(TEXT)
        p.setFont(font(20, QFont.Weight.Bold))
        p.drawText(214, 280, "0:14")
        x, y, w, _ = LOBBY_BUTTON_AREA
        p.drawImage(x + 10, y + 18, button(w - 20, 60, "CANCEL", CREAM, LOBBY_PANEL))
    party_panel(p, ["Ready", "Ready", "Open", "Open"])
    footer(p)
    return image, p


def party_panel(p: QPainter, rows: list[str]) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PANEL)
    p.drawRoundedRect(QRectF(680, 196, 240, 220), 10, 10)
    p.setPen(MUTED)
    p.setFont(font(12, QFont.Weight.DemiBold))
    p.drawText(700, 226, "PARTY")
    for i, status in enumerate(rows):
        y = 262 + i * 40
        p.setPen(QPen(LINE, 1))
        p.drawLine(700, y + 14, 900, y + 14)
        p.setPen(TEXT)
        p.setFont(font(14))
        p.drawText(700, y, f"Slot {i + 1}")
        p.setPen(MUTED)
        p.drawText(QRectF(780, y - 16, 120, 20), Qt.AlignmentFlag.AlignRight, status)


def results() -> tuple[QImage, QPainter]:
    image, p = canvas(W, H, RESULTS_BG)
    p.setPen(TEXT)
    p.setFont(font(34, QFont.Weight.Black, italic=True))
    p.drawText(360, 64, "YOU PLACED #12")
    p.setFont(font(16, QFont.Weight.Bold, italic=True))
    p.drawText(40, 40, "MATCH RECAP")
    p.setPen(QColor("#B9B2EE"))
    p.drawText(190, 40, "MATCH STATS")
    p.drawImage(600, 120, cosmetic_button(320, 44, RESULTS_BG))
    p.drawImage(600, 176, button(320, 44, "RETURN TO LOBBY", LAVENDER, RESULTS_BG, size=0.4))
    for i, mark in enumerate(("+", "-", "o", "*")):
        p.drawImage(600 + i * 82, 362, button(74, 44, mark, LAVENDER, RESULTS_BG, size=0.5))
    p.setPen(TEXT)
    p.setFont(font(22, QFont.Weight.Black))
    p.drawText(360, 330, "38,000 XP")
    # A promotion card with a yellow button of its own: Play Again's color, a different button.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(PROMO_BG)
    p.drawRect(QRectF(40, 380, 300, 132))
    p.setPen(TEXT)
    p.setFont(font(20, QFont.Weight.Black, italic=True))
    p.drawText(60, 420, "SEASON REWARDS")
    p.drawImage(60, 446, button(260, 36, "GET BATTLE PASS", YELLOW, PROMO_BG, size=0.45))
    footer(p, QColor("#B9B2EE"))
    return image, p


def spectating(sprites: dict[str, QImage]) -> tuple[QImage, QPainter]:
    image, p = canvas(W, H, SPECTATE_BG)
    p.fillRect(0, 0, W, 34, SPECTATE_BAR)
    p.fillRect(0, H - 44, W, 44, SPECTATE_BAR)
    p.setPen(TEXT)
    p.setFont(font(16, QFont.Weight.Black, italic=True))
    right = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
    p.drawText(QRectF(0, 0, W - 20, 34), right, "SPECTATING: PLAYER")
    p.setFont(font(40, QFont.Weight.Black, italic=True))
    p.drawText(QRectF(0, 220, W, 60), Qt.AlignmentFlag.AlignCenter, "READY")
    p.drawImage(550, 410, sprites["finding"])
    p.drawImage(20, H - 40, button(96, 34, "CANCEL", LAVENDER, SPECTATE_BAR, size=0.45))
    return image, p


def screens(sprites: dict[str, QImage]) -> None:
    out = ASSETS / "demo" / "screens"

    save(*lobby(sprites, matchmaking=False), out / "lobby.png")
    save(*lobby(sprites, matchmaking=True), out / "matchmaking.png")

    image, p = canvas(W, H, BG)
    p.setPen(TEXT)
    p.setFont(font(30, QFont.Weight.DemiBold))
    p.drawText(40, 62, "Loading")
    p.drawImage(370, 242, sprites["loading"])
    footer(p)
    save(image, p, out / "loading.png")

    image, p = canvas(W, H, QColor("#24402F"))
    p.setPen(TEXT)
    p.setFont(font(30, QFont.Weight.DemiBold))
    p.drawText(40, 62, "Match in progress")
    p.setPen(QColor("#B8D4C0"))
    p.setFont(font(15))
    p.drawText(40, 90, "LOOP waits until the match ends.")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1B2E22"))
    p.drawRoundedRect(QRectF(40, 300, 600, 10), 5, 5)
    p.setBrush(YELLOW)
    p.drawRoundedRect(QRectF(40, 300, 380, 10), 5, 5)
    footer(p, QColor("#B8D4C0"))
    save(image, p, out / "match.png")

    save(*results(), out / "results.png")
    save(*spectating(sprites), out / "finding.png")


def icon() -> None:
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#181A1F"))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    # A clockwise arc with an arrowhead: the "loop".
    center, radius, start, span = QPointF(128, 128), 64, 90, -290
    p.setPen(QPen(ACCENT, 24, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(64, 64, 128, 128), start * 16, span * 16)
    end = math.radians(start + span)
    tip = QPointF(center.x() + radius * math.cos(end), center.y() - radius * math.sin(end))
    tangent = QPointF(math.sin(end), math.cos(end))  # clockwise direction of travel
    normal = QPointF(math.cos(end), -math.sin(end))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawPolygon(
        QPolygonF(
            [
                tip + tangent * 30,
                tip + normal * 30 - tangent * 6,
                tip - normal * 30 - tangent * 6,
            ]
        )
    )
    p.end()
    for name in ("loop.png", "loop.ico"):
        if not image.save(str(ASSETS / name)):
            raise SystemExit(f"Could not write {name}")
        print("wrote", (ASSETS / name).relative_to(ROOT))


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - text rendering needs the platform font database
    screens(templates())
    icon()


if __name__ == "__main__":
    main()
