"""A small confirmation that a clip was captured.

Copy on select is deliberately invisible. It fires on a gesture that was being
made anyway, into whatever window happens to be in front, and that is the
point of it -- but it is also the problem. A feature whose whole job is to
read the clipboard should be visible when it acts, otherwise a clip that
worked and a clip that quietly did nothing look exactly alike. Before this,
the only feedback was a status line in the preview window, which is almost
never the window you are looking at when you highlight something.

So: a label near the cursor for about a second, then gone. Two things it must
never do. It must not take focus from the window the text was just selected
in, or the next keystroke goes somewhere unexpected; Qt.ToolTip plus
WA_ShowWithoutActivating covers that. And it must not swallow a mouse event
meant for that window, since it appears directly under the cursor by design;
that is WA_TransparentForMouseEvents.

No rounded corners, deliberately. A top-level widget with a border radius and
no translucent background paints garbage in the corners, and turning on
translucency to fix it is a compositing problem on exactly the machines least
able to afford one.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLabel

HOLD_MS = 950
FADE_MS = 320
CURSOR_OFFSET = (18, 22)
MARGIN = 6
SNIPPET_CHARS = 52

STYLE = """
QLabel {
    background: #1b1b1f;
    color: #e6e6ec;
    border: 1px solid #3a3a44;
    padding: 7px 10px;
    font-size: 11px;
}
"""


class ClipToast(QLabel):
    """Shows what was just copied, near the cursor, without stealing focus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Plain text, always: a clip is arbitrary text off the clipboard, and
        # QLabel's auto-detection would happily render <b>whatever</b> of it.
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet(STYLE)

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._fade)

        self._fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_out.setDuration(FADE_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade_out.finished.connect(self.hide)

    def show_clip(self, text: str, kind: str = "selection") -> None:
        """Announce a clip, restarting the timer if one is already showing."""
        self._hold.stop()
        self._fade_out.stop()
        self.setWindowOpacity(1.0)
        self.setText(summarise(text, kind))
        self.adjustSize()
        self.move(_position(self.width(), self.height()))
        self.show()
        self.raise_()
        self._hold.start(HOLD_MS)

    def _fade(self) -> None:
        if self.isVisible():
            self._fade_out.start()


def summarise(text: str, kind: str = "selection") -> str:
    """Two lines: what kind of clip and how big, then the clip itself."""
    count = len(text)
    label = kind if kind in ("word", "line") else "selection"
    unit = "character" if count == 1 else "characters"
    snippet = " ".join(text.split())
    if len(snippet) > SNIPPET_CHARS:
        snippet = snippet[: SNIPPET_CHARS - 3] + "..."
    header = f"{label} copied - {count} {unit}"
    return f"{header}\n{snippet}" if snippet else header


def _position(width: int, height: int) -> QPoint:
    """Below and right of the cursor, pushed back onto the screen if it lands off."""
    cursor = QCursor.pos()
    x = cursor.x() + CURSOR_OFFSET[0]
    y = cursor.y() + CURSOR_OFFSET[1]
    screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        x = max(area.left() + MARGIN, min(x, area.right() - width - MARGIN))
        y = max(area.top() + MARGIN, min(y, area.bottom() - height - MARGIN))
    return QPoint(x, y)
