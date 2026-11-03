"""The dimmed selection overlay.

One frameless window is placed over each screen. They share a single
SelectionController so a drag can cross monitor boundaries and every window
repaints the same selection rectangle.

## Why the drag does not trust the release event alone

Windows gives the mouse capture to the overlay the drag started on. When the
pointer crosses onto another monitor, and so onto a different overlay window,
that capture can be taken away: a second overlay getting activated, a DPI
boundary, the shell poking at a topmost window. Qt reports the lost capture as
a button release, even though the button is still held down. Before 0.4.4 that
release finished the snip on the spot, which is the snip that "ends by itself"
while dragging across or near the second screen.

So a release is checked against the physical button. If the button is still
down it is ignored, and from then on the drag is followed by polling the cursor,
because the window that lost the capture will not get the move events either.
The snip finishes once the button is really up.

The pointer position also comes from QCursor.pos() rather than from each
window's local event coordinates. Those are in the receiving window's scale, and
once the pointer is on a monitor with a different scale the rectangle would be
drawn in the wrong place.

## Why it is fast (0.8.0)

- The overlay windows are made once, ahead of time (`prewarm`), and kept
  hidden between snips. Making a full-screen native window is the slowest part
  of putting the overlay up, so a snip now only shows windows that already
  exist. A window is made on the spot only for a screen that was plugged in
  since.
- While dragging, only the strip of screen the rectangle and its size badge
  moved across is repainted, on the screens it touches, instead of every pixel
  of every screen on every mouse move. At 4K that is the difference between
  repainting 8 million pixels per move and a few thousand.

## Modes (0.12.0)

A bar at the top of each screen picks how to snip, as in Windows Snipping
Tool: **Rectangle** (R, drag a box), **Window** (W, hover a window and
click), **Freeform** (L, draw any shape; what is outside it is filled white),
and **Full screen** (F or Space, the screen the pointer is on). The mode is
remembered between snips; full screen is an action, not a mode. Window mode
gets its list of windows from winlist.py the first time it is needed, so a
snip in another mode never pays for it.
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtWidgets import QWidget

ACCENT = QColor(0, 160, 255)
HINT_BG = QColor(20, 20, 22, 210)
HINT_FG = QColor(240, 240, 245)

# How often the drag is followed by polling, in milliseconds. 10 ms is faster
# than the display refreshes, so the rectangle never visibly lags the pointer.
POLL_MS = 10
# How many polls in a row the button must read "up" before a drag whose
# release event was lost is finished. Guards against a single odd read.
RELEASE_CONFIRM_POLLS = 3

# The snip modes, in the order the bar shows them, with their keys.
MODES = ("rect", "window", "freeform")
MODE_NAMES = {"rect": "Rectangle", "window": "Window", "freeform": "Freeform"}
MODE_KEYS = {Qt.Key.Key_R: "rect", Qt.Key.Key_W: "window", Qt.Key.Key_L: "freeform"}
# Freeform: a new point only once the pointer has moved this far (logical px).
FREEFORM_STEP = 2

_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02
_SM_SWAPBUTTON = 23


def left_button_down() -> bool | None:
    """Whether the primary mouse button is physically held right now.

    None where this cannot be asked (not Windows), in which case the release
    event is trusted as before.

    GetAsyncKeyState reads the physical buttons, so with the buttons swapped
    for a left-handed mouse the primary button is VK_RBUTTON.
    """
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        vk = _VK_RBUTTON if user32.GetSystemMetrics(_SM_SWAPBUTTON) else _VK_LBUTTON
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)
    except (AttributeError, OSError):
        return None


class SelectionController(QObject):
    """Owns the overlay windows and the in-progress selection."""

    selected = Signal(QRect)
    cancelled = Signal()
    # The mode was changed on the bar or with a key (0.12.0), to remember it.
    mode_changed = Signal(str)

    def __init__(self, grabs, dim_opacity: int = 110, parent=None,
                 button_down=left_button_down, cursor_pos=QCursor.pos,
                 mode: str = "rect", window_source=None):
        super().__init__(parent)
        self.mode = mode if mode in MODES else "rect"
        # Window mode: where the windows are (topmost first), asked once.
        self._window_source = window_source
        self._windows_on_screen: list[QRect] | None = None
        self.hover_window: QRect | None = None
        # Freeform: the points drawn so far, global logical coordinates.
        self.path: list[QPoint] = []
        # A short line the bar shows (no windows found, and so on).
        self.notice = ""
        self._grabs = grabs
        self._dim = dim_opacity
        self._windows: list[OverlayWindow] = []
        self._origin: QPoint | None = None
        self._current = QRect()
        self._finished = False
        # Injected so the drag logic can be tested without a mouse.
        self._button_down = button_down
        self._cursor_pos = cursor_pos
        # Set once a release arrived while the button was still held: from
        # then on no trustworthy release event is coming, so polling decides.
        self._release_lost = False
        self._up_polls = 0
        self._last_polled: QPoint | None = None
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.poll)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        for grab in self._grabs:
            window = _window_for(grab.screen)
            window.attach(grab, self, self._dim)
            self._windows.append(window)
            # A reused window still holds the last snip's picture. Kept out of
            # the compositor until it has painted this one, so that picture is
            # never seen, not even for a frame.
            _cloak(window, True)
            window.show()
        for window in self._windows:
            window.repaint()
            _cloak(window, False)
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
        self._poll.stop()
        for window in self._windows:
            # Hidden, not destroyed: the next snip shows it again straight away.
            window.release_grab()
        self._windows.clear()

    # -- selection state ---------------------------------------------------
    @property
    def selection(self) -> QRect:
        return self._current

    @property
    def shape(self) -> QPolygon | None:
        """Freeform: the outline drawn, once it is one. None for other modes."""
        if self.mode != "freeform" or len(self.path) < 3:
            return None
        return QPolygon(self.path)

    @property
    def dragging(self) -> bool:
        return self._origin is not None and not self._finished

    # -- modes (0.12.0) ----------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode not in MODES or self.dragging:
            return
        self.notice = ""
        if mode == "window" and not self.windows():
            self.notice = "No windows found to snip here; drag a rectangle instead."
            mode = "rect"
        changed = mode != self.mode
        self.mode = mode
        self.hover_window = None
        if mode == "window":
            self.hover(self._cursor_pos())
        self._repaint()
        if changed:
            self.mode_changed.emit(mode)

    def windows(self) -> list[QRect]:
        if self._windows_on_screen is None:
            try:
                self._windows_on_screen = list(self._window_source() if self._window_source else [])
            except Exception:  # noqa: BLE001 - window snips are an extra
                self._windows_on_screen = []
        return self._windows_on_screen

    def hover(self, global_pos: QPoint) -> None:
        """Window mode: light up the window under the pointer."""
        if self.mode != "window" or self._finished:
            return
        from winlist import window_at

        found = window_at(self.windows(), global_pos)
        if found != self.hover_window:
            before = self.hover_window or QRect()
            self.hover_window = found
            self._repaint_between(before, found or QRect())

    def click_window(self) -> None:
        """Window mode: take the window under the pointer."""
        if self._finished:
            return
        self.hover(self._cursor_pos())
        if self.hover_window is None:
            return
        self._finished = True
        rect = QRect(self.hover_window)
        self.close_all()
        self.selected.emit(rect)

    @property
    def release_lost(self) -> bool:
        return self._release_lost

    def begin(self, global_pos: QPoint) -> None:
        self._origin = global_pos
        self._current = QRect(global_pos, global_pos)
        self.path = [QPoint(global_pos)]
        self._release_lost = False
        self._up_polls = 0
        self._last_polled = None
        # The hint disappears once a drag starts, so this one repaint is whole.
        self._repaint()
        if self._button_down is not None:
            self._poll.start()

    def release(self) -> None:
        """A window reported the button going up. Finish, unless it did not.

        A release while the button is physically still held is Windows taking
        the capture away mid-drag, not the user letting go.
        """
        if self._finished or self._origin is None:
            self.finish()
            return
        held = self._button_down() if self._button_down is not None else None
        if held:
            self._release_lost = True
            self._up_polls = 0
            return
        self.finish()

    def poll(self) -> None:
        """Follow the pointer, and notice a release no window was told about."""
        if self._finished or self._origin is None:
            self._poll.stop()
            return
        pos = self._cursor_pos()
        if pos != self._last_polled:
            self._last_polled = pos
            self.drag_to(pos)
        if not self._release_lost:
            return
        held = self._button_down() if self._button_down is not None else None
        if held is False:
            self._up_polls += 1
            if self._up_polls >= RELEASE_CONFIRM_POLLS:
                self.finish()
        else:
            self._up_polls = 0

    def drag_to(self, global_pos: QPoint) -> None:
        if self._origin is None:
            return
        before = self._current
        if self.mode == "freeform":
            last = self.path[-1]
            if abs(global_pos.x() - last.x()) + abs(global_pos.y() - last.y()) < FREEFORM_STEP:
                return
            self.path.append(QPoint(global_pos))
            self._current = QPolygon(self.path).boundingRect()
        else:
            self._current = QRect(self._origin, global_pos).normalized()
        if self._current != before:
            self._repaint_between(before, self._current)

    def finish(self) -> None:
        if self._finished:
            return
        rect = self._current
        if self.mode == "freeform" and self.shape is None:
            rect = QRect()
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

    def _repaint_between(self, before: QRect, after: QRect) -> None:
        """Repaint only where the rectangle was and where it is now."""
        dirty = _with_badge(before).united(_with_badge(after))
        for window in self._windows:
            window.update_global(dirty)


# Room around a selection for its 1 px border and the size badge, which sits
# above the rectangle (or below it near the top of the screen).
_BADGE_W = 220
_BADGE_H = 40


def _with_badge(rect: QRect) -> QRect:
    if rect.isNull():
        return QRect()
    return rect.adjusted(-4, -_BADGE_H - 4, 4, _BADGE_H + 4).united(
        QRect(rect.x() - 4, rect.y() - _BADGE_H - 4, _BADGE_W, _BADGE_H * 2 + rect.height() + 8)
    )


# DWMWA_CLOAK: keeps a shown window out of the composed desktop (Windows 8+).
_DWMWA_CLOAK = 13


def _cloak(window: QWidget, on: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        value = ctypes.c_int(1 if on else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(window.winId())), _DWMWA_CLOAK,
            ctypes.byref(value), ctypes.sizeof(value),
        )
    except (AttributeError, OSError, ValueError):
        pass


# -- the window pool ----------------------------------------------------------------------------
# One overlay window per screen, made ahead of time and reused for every snip.
_POOL: dict[tuple, "OverlayWindow"] = {}


def _screen_key(screen) -> tuple:
    g = screen.geometry()
    return (screen.name(), g.x(), g.y(), g.width(), g.height())


def _window_for(screen) -> "OverlayWindow":
    key = _screen_key(screen)
    window = _POOL.get(key)
    if window is None:
        window = OverlayWindow(None, None, 0, screen=screen)
        _POOL[key] = window
    return window


def prewarm() -> int:
    """Make the overlay windows now, hidden, so the first snip does not wait.

    Windows for screens that are no longer connected (or have moved or changed
    resolution) are dropped. Returns how many windows are ready.
    """
    from PySide6.QtGui import QGuiApplication

    live = {_screen_key(s): s for s in QGuiApplication.screens()}
    for key in [k for k in _POOL if k not in live]:
        window = _POOL.pop(key)
        if not window.isVisible():
            window.deleteLater()
    for key, screen in live.items():
        window = _window_for(screen)
        window.winId()  # creates the native window without showing it
    return len(_POOL)


# -- the mode bar (0.12.0) -----------------------------------------------------------------------
BAR_TOP = 14
BAR_HEIGHT = 34
BAR_ITEMS = (
    ("rect", "Rectangle", "R"),
    ("window", "Window", "W"),
    ("freeform", "Freeform", "L"),
    ("screen", "Full screen", "F"),
    ("close", "Esc", ""),
)


def _bar_font() -> QFont:
    font = QFont()
    font.setPointSizeF(9.5)
    return font


def bar_layout(screen_width: int) -> list[tuple[str, QRect]]:
    """Each bar button's rectangle, in a screen's local coordinates, centred at the top."""
    from PySide6.QtGui import QFontMetrics

    metrics = QFontMetrics(_bar_font())
    widths = []
    for _key, label, letter in BAR_ITEMS:
        text = f"{label}  {letter}" if letter else label
        widths.append(metrics.horizontalAdvance(text) + 26)
    total = sum(widths) + 4 * (len(widths) - 1) + 12
    x = int((screen_width - total) / 2) + 6
    out = []
    for (key, _label, _letter), width in zip(BAR_ITEMS, widths):
        out.append((key, QRect(x, BAR_TOP + 4, width, BAR_HEIGHT - 8)))
        x += width + 4
    return out


def bar_rect(screen_width: int) -> QRect:
    items = bar_layout(screen_width)
    left, right = items[0][1].left() - 6, items[-1][1].right() + 6
    return QRect(left, BAR_TOP, right - left + 1, BAR_HEIGHT)


class OverlayWindow(QWidget):
    def __init__(self, grab, controller: SelectionController | None, dim: int, screen=None):
        super().__init__(None)
        self.grab_info = grab
        self.controller = controller
        self.dim = dim
        self._show_hint = True
        screen = screen if screen is not None else grab.screen
        self._screen = screen

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Every pixel is painted each time, so Qt need not clear first.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(screen.geometry())
        self.winId()
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)

    def attach(self, grab, controller: SelectionController, dim: int) -> None:
        """Take on a new frozen frame for the next snip."""
        self.grab_info = grab
        self.controller = controller
        self.dim = dim
        self._show_hint = True
        if self.geometry() != grab.screen.geometry():
            self.setGeometry(grab.screen.geometry())

    def release_grab(self) -> None:
        """Hide until the next snip, and let go of the frozen frame's memory."""
        self.hide()
        self.grab_info = None
        self.controller = None

    def update_global(self, rect: QRect) -> None:
        """Repaint the part of `rect` (global, logical) that lies on this screen."""
        if self.grab_info is None:
            return
        geom = self.grab_info.screen.geometry()
        local = rect.translated(-geom.x(), -geom.y()).intersected(self.rect())
        if not local.isEmpty():
            self.update(local)

    # -- input -------------------------------------------------------------
    def _to_global(self, pos: QPoint) -> QPoint:
        geom = self.grab_info.screen.geometry()
        return QPoint(geom.x() + pos.x(), geom.y() + pos.y())

    def _bar_item_at(self, pos: QPoint) -> str | None:
        if self.controller is None or self.controller.dragging:
            return None
        for key, rect in bar_layout(self.width()):
            if rect.contains(pos):
                return key
        return None

    def mousePressEvent(self, event):
        if self.controller is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.controller.cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        item = self._bar_item_at(pos)
        if item == "close":
            self.controller.cancel()
        elif item == "screen":
            self.controller.take_screen(self.grab_info.screen.geometry())
        elif item is not None:
            self.controller.set_mode(item)
        elif self.controller.mode == "window":
            self.controller.click_window()
        else:
            self._show_hint = False
            self.controller.begin(self._to_global(pos))

    def mouseMoveEvent(self, event):
        if self.controller is None:
            return
        hot = self._bar_item_at(event.position().toPoint())
        if hot != getattr(self, "_bar_hot", None):
            self._bar_hot = hot
            self.update(bar_rect(self.width()))
        if self.controller.mode == "window" and not self.controller.dragging:
            self.controller.hover(QCursor.pos())
            return
        if event.buttons() & Qt.MouseButton.LeftButton or self.controller.release_lost:
            # The global cursor position, not this window's local coordinates:
            # after the pointer crosses onto another monitor the events can
            # still arrive here, scaled for this monitor rather than that one.
            self.controller.drag_to(QCursor.pos())

    def mouseReleaseEvent(self, event):
        if self.controller is None:
            return
        # Only a drag ends on release. A click on the mode bar or on a window
        # (0.12.0) has already done its work on the press, and a release
        # with no drag behind it would otherwise read as an empty snip and
        # cancel the whole thing.
        if event.button() == Qt.MouseButton.LeftButton and self.controller.dragging:
            self.controller.release()

    def keyPressEvent(self, event):
        if self.controller is None:
            return super().keyPressEvent(event)
        key = event.key()
        if key in MODE_KEYS:
            self.controller.set_mode(MODE_KEYS[key])
        elif key == Qt.Key.Key_Escape:
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
        if self.grab_info is None or self.controller is None:
            painter.fillRect(event.rect(), QColor(0, 0, 0))
            painter.end()
            return
        pixmap: QPixmap = self.grab_info.pixmap
        scale = self.grab_info.scale
        geom = self.grab_info.screen.geometry()

        # Only the part Qt asked for: a drag repaints a thin strip, not the screen.
        area = event.rect().intersected(self.rect())
        painter.drawPixmap(QRectF(area), pixmap, _device_rect(area, scale))
        painter.fillRect(area, QColor(0, 0, 0, self.dim))

        controller = self.controller
        if controller.mode == "window":
            self._paint_window(painter, area, pixmap, scale, geom)
        elif controller.mode == "freeform" and controller.dragging and len(controller.path) > 1:
            self._paint_freeform(painter, area, pixmap, scale, geom)
        else:
            selection = controller.selection
            local = selection.translated(-geom.x(), -geom.y()).intersected(self.rect())
            if not local.isEmpty():
                bright = local.intersected(area)
                if not bright.isEmpty():
                    painter.drawPixmap(QRectF(bright), pixmap, _device_rect(bright, scale))
                pen = QPen(ACCENT)
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawRect(local.adjusted(0, 0, -1, -1))
                self._draw_size_badge(painter, local, selection)
        if not controller.dragging and area.intersects(bar_rect(self.width()).adjusted(0, 0, 0, 40)):
            self._draw_bar(painter)
        painter.end()

    def _paint_window(self, painter, area, pixmap, scale, geom) -> None:
        """The window under the pointer, bright and outlined, with its size."""
        window = self.controller.hover_window
        if window is None:
            return
        local = window.translated(-geom.x(), -geom.y()).intersected(self.rect())
        if local.isEmpty():
            return
        bright = local.intersected(area)
        if not bright.isEmpty():
            painter.drawPixmap(QRectF(bright), pixmap, _device_rect(bright, scale))
        painter.setPen(QPen(ACCENT, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(local.adjusted(1, 1, -1, -1))
        self._draw_size_badge(painter, local, window)

    def _paint_freeform(self, painter, area, pixmap, scale, geom) -> None:
        """Inside the shape drawn so far bright, the outline in the accent colour."""
        local = QPolygon([QPoint(p.x() - geom.x(), p.y() - geom.y()) for p in self.controller.path])
        path = QPainterPath()
        path.addPolygon(_polygon_f(local))
        path.closeSubpath()
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(QRectF(area), pixmap, _device_rect(area, scale))
        painter.restore()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(ACCENT, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(local)
        bounds = self.controller.selection
        self._draw_size_badge(painter, bounds.translated(-geom.x(), -geom.y()), bounds)

    def _draw_bar(self, painter: QPainter) -> None:
        """The mode bar: the current mode lit, the one under the pointer outlined."""
        controller = self.controller
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(_bar_font())
        frame = bar_rect(self.width())
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(QRectF(frame), 8, 8)
        hot = getattr(self, "_bar_hot", None)
        for (key, label, letter), (_key, rect) in zip(BAR_ITEMS, bar_layout(self.width())):
            current = key == controller.mode
            if current:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 200))
                painter.drawRoundedRect(QRectF(rect), 5, 5)
            elif key == hot:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 28))
                painter.drawRoundedRect(QRectF(rect), 5, 5)
            painter.setPen(HINT_FG)
            text = f"{label}  {letter}" if letter else label
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        if controller.notice or controller.mode == "window":
            line = controller.notice or "Click a window to snip it"
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(line) + 20
            box = QRect(int((self.width() - width) / 2), frame.bottom() + 6, width, metrics.height() + 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HINT_BG)
            painter.drawRoundedRect(QRectF(box), 5, 5)
            painter.setPen(HINT_FG)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, line)
        painter.restore()

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


def _polygon_f(polygon: QPolygon):
    from PySide6.QtGui import QPolygonF

    return QPolygonF([QPointF(p) for p in polygon])


def _device_rect(local: QRect, scale: float) -> QRectF:
    """`local` (logical, on one screen) in that screen's grabbed pixels."""
    return QRectF(local.x() * scale, local.y() * scale, local.width() * scale, local.height() * scale)
