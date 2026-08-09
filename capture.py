"""Freeze-frame screen capture.

ShadowSnip grabs every screen up front, then draws the frozen frames under the
selection overlay. That way the picture cannot change while the user is
dragging, and the crop is taken from real pixels rather than a re-grab.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtGui import QScreen


@dataclass
class ScreenGrab:
    screen: QScreen
    pixmap: QPixmap
    scale: float  # device pixels per logical pixel for this screen


def grab_all_screens() -> list[ScreenGrab]:
    """Capture every connected screen. Returns one ScreenGrab per screen."""
    grabs: list[ScreenGrab] = []
    for screen in QGuiApplication.screens():
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            continue
        geom = screen.geometry()
        # Derive the scale from the pixels we actually got rather than trusting
        # devicePixelRatio, which differs between Qt versions and DPI modes.
        scale = pixmap.width() / geom.width() if geom.width() else 1.0
        if scale <= 0:
            scale = 1.0
        grabs.append(ScreenGrab(screen=screen, pixmap=pixmap, scale=scale))
    return grabs


def virtual_geometry() -> QRect:
    """Bounding rectangle of all screens, in logical coordinates."""
    rect = QRect()
    for screen in QGuiApplication.screens():
        rect = rect.united(screen.geometry())
    return rect


def compose_selection(grabs: list[ScreenGrab], rect: QRect) -> QImage | None:
    """Cut `rect` (logical, global coordinates) out of the frozen frames.

    A selection may span screens with different scale factors; the result is
    rendered at the highest scale involved so nothing is thrown away.
    """
    if rect.isEmpty():
        return None

    parts = []
    for grab in grabs:
        overlap = grab.screen.geometry().intersected(rect)
        if overlap.isEmpty():
            continue
        parts.append((grab, overlap))
    if not parts:
        return None

    out_scale = max(grab.scale for grab, _ in parts)
    width = max(1, round(rect.width() * out_scale))
    height = max(1, round(rect.height() * out_scale))

    out = QImage(width, height, QImage.Format.Format_RGB32)
    out.fill(0xFF000000)

    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for grab, overlap in parts:
        geom = grab.screen.geometry()
        local = QRect(
            overlap.x() - geom.x(),
            overlap.y() - geom.y(),
            overlap.width(),
            overlap.height(),
        )
        source = QRect(
            round(local.x() * grab.scale),
            round(local.y() * grab.scale),
            max(1, round(local.width() * grab.scale)),
            max(1, round(local.height() * grab.scale)),
        )
        target = QRectF(
            (overlap.x() - rect.x()) * out_scale,
            (overlap.y() - rect.y()) * out_scale,
            overlap.width() * out_scale,
            overlap.height() * out_scale,
        )
        painter.drawImage(target, grab.pixmap.copy(source).toImage())
    painter.end()
    return out
