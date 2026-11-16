"""What is on screen while a clip records (0.14.0): a frame around the area and a control bar.

- The **frame** is four thin red bars just outside the area, so it shows what
  is being recorded without being in the recording.
- The **bar** shows the time, and Pause and Stop. It sits below the area, or
  above it, or failing both inside its bottom edge (a full-screen clip).

Neither ever takes focus: clicking Pause must not pull focus from the program
being recorded, and a menu open in it must stay open.

On Windows both are marked `WDA_EXCLUDEFROMCAPTURE` (Windows 10 2004 and
later), so screen grabs see through them: even a bar inside a full-screen clip
is not in it. On Linux they are left out by staying outside the area, which a
full-screen clip cannot do; there the bar can be seen in the clip.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

import clips

FRAME_WIDTH = 3
FRAME_GAP = 2
FRAME_COLOUR = QColor("#e81123")
BAR_GAP = 10

BAR_STYLE = """
QWidget#RecordBar { background: #1b1b1f; border: 1px solid #3a3a44; border-radius: 8px; }
QLabel { color: #e6e6ec; font-size: 13px; }
QLabel#Dot { color: #e81123; font-size: 15px; }
QPushButton {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44; border-radius: 5px;
    padding: 4px 12px; font-size: 12px;
}
QPushButton:hover { background: #33333b; }
QPushButton#Stop { background: #a4001d; border-color: #c2002a; color: #ffffff; }
QPushButton#Stop:hover { background: #c2002a; }
"""

WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_from_capture(widget: QWidget) -> bool:
    """Ask Windows to leave this window out of screen grabs. False elsewhere or if refused."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except (AttributeError, OSError):
        return False


def _overlay_flags() -> Qt.WindowType:
    return (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)


class _Edge(QWidget):
    def __init__(self):
        super().__init__(None, _overlay_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), FRAME_COLOUR)
        painter.end()


class RecordingFrame:
    """Four bars just outside `rect` (global logical coordinates)."""

    def __init__(self, rect: QRect):
        self.rect = QRect(rect)
        self.edges = [_Edge() for _ in range(4)]
        for edge, geometry in zip(self.edges, frame_edges(self.rect)):
            edge.setGeometry(geometry)

    def show(self) -> None:
        for edge in self.edges:
            edge.show()
            exclude_from_capture(edge)

    def close(self) -> None:
        for edge in self.edges:
            edge.close()


def frame_edges(rect: QRect) -> list[QRect]:
    """Top, bottom, left, right bars around `rect`, outside it by FRAME_GAP."""
    out = FRAME_GAP + FRAME_WIDTH
    left, top = rect.left() - out, rect.top() - out
    width = rect.width() + 2 * out
    return [
        QRect(left, top, width, FRAME_WIDTH),
        QRect(left, rect.bottom() + 1 + FRAME_GAP, width, FRAME_WIDTH),
        QRect(left, rect.top() - FRAME_GAP, FRAME_WIDTH, rect.height() + 2 * FRAME_GAP),
        QRect(rect.right() + 1 + FRAME_GAP, rect.top() - FRAME_GAP, FRAME_WIDTH, rect.height() + 2 * FRAME_GAP),
    ]


def bar_place(rect: QRect, size, screen: QRect) -> QPoint:
    """Where the bar goes: centred below the area, else above, else inside its bottom."""
    x = rect.center().x() - size.width() // 2
    x = max(screen.left() + 4, min(x, screen.right() - size.width() - 4))
    below = rect.bottom() + 1 + FRAME_GAP + FRAME_WIDTH + BAR_GAP
    if below + size.height() <= screen.bottom():
        return QPoint(x, below)
    above = rect.top() - FRAME_GAP - FRAME_WIDTH - BAR_GAP - size.height()
    if above >= screen.top():
        return QPoint(x, above)
    return QPoint(x, rect.bottom() - size.height() - BAR_GAP)


class RecordingBar(QWidget):
    """The time, Pause and Stop, beside the area being recorded."""

    pause_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, microphone: bool = False):
        super().__init__(None, _overlay_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("RecordBar")
        self.setStyleSheet(BAR_STYLE)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setObjectName("Dot")
        self.time = QLabel("0:00")
        self.mic = QLabel("\U0001f3a4 mic on" if microphone else "")
        self.mic.setVisible(microphone)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_pause.clicked.connect(self.pause_clicked.emit)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("Stop")
        self.btn_stop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_stop.setToolTip("Stop and save the clip (or press the clip hotkey again)")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        for widget in (self.dot, self.time, self.mic, self.btn_pause, self.btn_stop):
            layout.addWidget(widget)
        self.adjustSize()

    def show_seconds(self, seconds: int) -> None:
        self.time.setText(clips.format_length(seconds))

    def set_paused(self, paused: bool) -> None:
        self.btn_pause.setText("Resume" if paused else "Pause")
        self.dot.setStyleSheet("color: #8e8e9a;" if paused else "")

    def place_beside(self, rect: QRect, screen: QRect) -> None:
        self.adjustSize()
        self.move(bar_place(rect, self.size(), screen))

    def show(self) -> None:
        super().show()
        exclude_from_capture(self)
