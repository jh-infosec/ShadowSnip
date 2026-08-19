"""The dimmed selection overlay.

One frameless window is placed over each screen. They share a single
SelectionController so a drag can cross monitor boundaries and every window
repaints the same selection rectangle.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

ACCENT = QColor(0, 160, 255)
HINT_BG = QColor(20, 20, 22, 210)
HINT_FG = QColor(240, 240, 245)


class SelectionController(QObject):
    """Owns the overlay windows and the in-progress selection."""

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, grabs, dim_opacity: int = 110, parent=None):
        super().__init__(parent)
        self._grabs = grabs
        self._dim = dim_opacity
        self._windows: list[OverlayWindow] = []
        self._origin: QPoint | None = None
        self._current = QRect()
        self._finished = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        for grab in self._grabs:
            window = OverlayWindow(grab, self, self._dim)
            self._windows.append(window)
            window.show()
        if self._windows:
            # Focus the overlay the pointer is actually on, so F and Space grab
            # that screen rather than whichever one Windows calls primary.
            cursor = QCursor.pos()
            for window in self._windows:
                if window.grab_info.screen.geometry().contains(cursor):
                    window.activateWindow()
                    window.raise_()
                    break
            else:
                self._windows[0].activateWindow()
                self._windows[0].raise_()

    def close_all(self) -> None:
        for window in self._windows:
            window.close()
        self._windows.clear()

    # -- selection state ---------------------------------------------------
    @property
    def selection(self) -> QRect:
        return self._current

    def begin(self, global_pos: QPoint) -> None:
        self._origin = global_pos
        self._current = QRect(global_pos, global_pos)
        self._repaint()

    def drag_to(self, global_pos: QPoint) -> None:
        if self._origin is None:
            return
        self._current = QRect(self._origin, global_pos).normalized()
        self._repaint()

    def finish(self) -> None:
        if self._finished:
            return
        rect = self._current
        if self._origin is None or rect.width() < 3 or rect.height() < 3:
            self.cancel()
            return
        self._finished = True
        self.close_all()
        self.selected.emit(rect)

    def take_screen(self, screen_geometry: QRect) -> None:
        """Grab a whole screen without dragging."""
        if self._finished:
            return
        self._finished = True
        self.close_all()
        self.selected.emit(screen_geometry)

    def cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.close_all()
        self.cancelled.emit()

    def _repaint(self) -> None:
        for window in self._windows:
            window.update()


class OverlayWindow(QWidget):
    def __init__(self, grab, controller: SelectionController, dim: int):
        super().__init__(None)
        self.grab_info = grab
        self.controller = controller
        self.dim = dim
        self._show_hint = True

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(grab.screen.geometry())
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(grab.screen)

    # -- input -------------------------------------------------------------
    def _to_global(self, pos: QPoint) -> QPoint:
        geom = self.grab_info.screen.geometry()
        return QPoint(geom.x() + pos.x(), geom.y() + pos.y())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.controller.cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._show_hint = False
            self.controller.begin(self._to_global(event.position().toPoint()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.controller.drag_to(self._to_global(event.position().toPoint()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.controller.finish()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.controller.cancel()
        elif key in (Qt.Key.Key_F, Qt.Key.Key_Space):
            self.controller.take_screen(self.grab_info.screen.geometry())
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.controller.finish()
        else:
            super().keyPressEvent(event)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        pixmap: QPixmap = self.grab_info.pixmap
        scale = self.grab_info.scale
        geom = self.grab_info.screen.geometry()

        painter.drawPixmap(self.rect(), pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, self.dim))

        selection = self.controller.selection
        local = selection.translated(-geom.x(), -geom.y()).intersected(self.rect())
        if not local.isEmpty():
            source = QRect(
                round(local.x() * scale),
                round(local.y() * scale),
                max(1, round(local.width() * scale)),
                max(1, round(local.height() * scale)),
            )
            painter.drawPixmap(local, pixmap, source)
            pen = QPen(ACCENT)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(local.adjusted(0, 0, -1, -1))
            self._draw_size_badge(painter, local, selection)
        elif self._show_hint:
            self._draw_hint(painter)
        painter.end()

    def _draw_size_badge(self, painter: QPainter, local: QRect, selection: QRect):
        text = f"{selection.width()} x {selection.height()}"
        font = QFont()
        font.setPointSizeF(9.5)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pad = 6
        width = metrics.horizontalAdvance(text) + pad * 2
        height = metrics.height() + pad
        x = local.x()
        y = local.y() - height - 4
        if y < 0:
            y = min(local.bottom() + 4, self.height() - height)
        x = max(0, min(x, self.width() - width))
        badge = QRect(int(x), int(y), int(width), int(height))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(HINT_FG)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_hint(self, painter: QPainter):
        text = "Drag to snip     F for this whole screen     Esc to cancel"
        font = QFont()
        font.setPointSizeF(10.5)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 28
        height = metrics.height() + 16
        box = QRect(
            int((self.width() - width) / 2),
            int(self.height() * 0.08),
            int(width),
            int(height),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(HINT_FG)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
