"""The countdown before a delayed snip (0.13.0).

A delayed snip exists to catch what vanishes the moment ShadowSnip is used:
a right-click menu, a tooltip, a hover state, a dropdown. So while it counts
down, the countdown must stay out of the way of whatever is being opened:

- It never takes focus (a menu closes when another window is activated) and
  never catches the mouse (it may sit where a click is wanted), the same two
  rules toast.py follows.
- It sits in the bottom right corner of the screen the pointer is on, away
  from where menus and tooltips usually open.
- It is gone before the screen is frozen: the app hides it, waits a moment
  for the compositor, and only then starts the snip.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLabel

# Delays offered in the menus, in seconds.
DELAYS = (3, 5, 10)
# The longest delay accepted from the command line.
MAX_DELAY = 60
MARGIN = 18

STYLE = """
QLabel {
    background: #1b1b1f;
    color: #e6e6ec;
    border: 1px solid #3a3a44;
    padding: 8px 14px;
    font-size: 13px;
}
"""


class Countdown(QLabel):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(STYLE)

    def show_seconds(self, seconds: int) -> None:
        self.setText(f"Snipping in {seconds}...")
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(QPoint(area.right() - self.width() - MARGIN, area.bottom() - self.height() - MARGIN))
        if not self.isVisible():
            self.show()
        self.raise_()


def parse_delay(args: list[str]) -> int:
    """The seconds after `--delay` (or `--delay=N`) in `args`; 0 when absent or not a number."""
    for index, arg in enumerate(args):
        value = None
        if arg == "--delay" and index + 1 < len(args):
            value = args[index + 1]
        elif arg.startswith("--delay="):
            value = arg.split("=", 1)[1]
        if value is not None:
            try:
                return max(0, min(MAX_DELAY, int(value)))
            except ValueError:
                return 0
    return 0
