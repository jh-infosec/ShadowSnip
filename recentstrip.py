"""The recent strip (0.19.0): the last few snips as thumbnails under the picture.

One click puts that snip back on the clipboard, the way it was copied the
first time, without finding it in the list. Double-click opens it full size,
right-click has Copy, Copy as and Expand. In a lab it shows the lab's newest
snips, otherwise your recent ones: the same rows as the snip list, newest
first. Clips show their poster, and copy as their video file.

The strip only shows and signals. The window does the copying, through the
snip list, so a copy from here is exactly a copy from the list.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

import skins

COUNT = 8
THUMB = QSize(88, 54)

STYLE = """
QToolButton#RecentTile {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 6px;
    padding: 3px;
}
QToolButton#RecentTile:hover {
    border: 1px solid #2f8cff;
    background: rgba(255, 255, 255, 0.08);
}
QLabel#RecentTitle { color: #9aa3ad; font-size: 11px; }
"""


def _is_clip(row: dict) -> bool:
    import clips

    return bool(row.get("path")) and clips.clip_for(row.get("path")) is not None


def newest(rows, count: int = COUNT) -> list[dict]:
    """The newest `count` rows (rows come oldest first, as lab.snip_rows gives them)."""
    return list(reversed(list(rows)))[:count]


class RecentStrip(QWidget):
    """A row of the newest snips. Click to copy, double-click to expand."""

    # A snip's file name, to copy again.
    copy_requested = Signal(str)
    # (file, format): Copy as.
    copy_as_requested = Signal(str, str)
    # A snip's file name, to show full size.
    expand_requested = Signal(str)

    def __init__(self, thumbs=None, parent=None):
        super().__init__(parent)
        self.setObjectName("RecentStrip")
        if thumbs is None:
            from labsnips import ThumbCache

            thumbs = ThumbCache()
        self._thumbs = thumbs
        self._rows: list[dict] = []
        self.title = QLabel("Recent")
        self.title.setObjectName("RecentTitle")
        self.title.setToolTip("Click a snip to copy it again, double-click to open it, right-click for more")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addWidget(self.title)
        # A fixed set of tiles, filled in afresh each time rather than made
        # and deleted: the list is refreshed on every snip, and tiles deleted
        # while their click was still being handled are how Qt programs crash.
        self._pool: list[_Tile] = []
        for _ in range(COUNT):
            tile = _Tile("")
            tile.setObjectName("RecentTile")
            tile.setIconSize(THUMB)
            tile.clicked.connect(lambda _c=False, t=tile: t.filename and self.copy_requested.emit(t.filename))
            tile.double_clicked.connect(self.expand_requested.emit)
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda pos, t=tile: self._menu(t, pos))
            tile.hide()
            self._layout.addWidget(tile)
            self._pool.append(tile)
        self._layout.addStretch(1)
        self.restyle()

    @property
    def tiles(self) -> list:
        """The tiles in use, newest first (some may be hidden when the window is narrow)."""
        return [tile for tile in self._pool if tile.filename]

    def restyle(self) -> None:
        self.setStyleSheet(skins.style(STYLE))

    def set_rows(self, rows) -> None:
        """Show the newest snips from these rows (oldest first, as the list takes them)."""
        from PySide6.QtGui import QIcon

        self._rows = newest(rows)
        ratio = self.devicePixelRatioF()
        for index, tile in enumerate(self._pool):
            row = self._rows[index] if index < len(self._rows) else None
            if row is None:
                tile.filename = ""
                tile.setIcon(QIcon())
                tile.hide()
                continue
            tile.filename = row.get("file", "")
            path = row.get("path") or ""
            pixmap = self._thumbs.get(str(path), THUMB, ratio) if path else None
            tile.setIcon(QIcon(pixmap) if pixmap is not None and not pixmap.isNull() else QIcon())
            tile.setToolTip(self._tooltip(row))
        self._fit()
        self.setVisible(bool(self._rows) and self._wanted)

    def _fit(self) -> None:
        """Show as many of the newest as fit the width, never a tile cut off at the edge."""
        used = [tile for tile in self._pool if tile.filename]
        if not used:
            for tile in self._pool:
                tile.hide()
            return
        step = used[0].sizeHint().width() + self._layout.spacing()
        room = self.width() - self.title.sizeHint().width() - self._layout.spacing()
        fits = max(1, room // max(1, step)) if self.width() > 0 else len(used)
        for index, tile in enumerate(self._pool):
            tile.setVisible(bool(tile.filename) and index < fits)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    _wanted = True

    def set_wanted(self, on: bool) -> None:
        """Settings: show the strip at all."""
        self._wanted = bool(on)
        self.setVisible(bool(self._rows) and self._wanted)

    def clear(self) -> None:
        self.set_rows([])

    def files(self) -> list[str]:
        return [tile.filename for tile in self.tiles]

    def _tooltip(self, row: dict) -> str:
        name = row.get("file", "")
        number = row.get("number")
        label = f"{int(number):03d}" if isinstance(number, int) else name.split("_", 1)[0]
        kind = "clip" if _is_clip(row) else "snip"
        caption = str(row.get("caption") or "").strip()
        lines = [f"{kind.capitalize()} {label}"]
        if caption:
            lines.append(caption)
        lines.append("Click to copy it again, double-click to open it")
        return "\n".join(lines)

    def _menu(self, tile: "_Tile", pos) -> None:
        import annotate
        import copyas

        menu = QMenu(self)
        menu.setStyleSheet(skins.style(annotate.MENU_STYLE))
        menu.addAction("Copy", lambda: self.copy_requested.emit(tile.filename))
        row = next((r for r in self._rows if r.get("file") == tile.filename), {})
        if not _is_clip(row):
            sub = menu.addMenu("Copy as")
            sub.setStyleSheet(skins.style(annotate.MENU_STYLE))
            for fmt, label in copyas.FORMATS:
                sub.addAction(label).triggered.connect(
                    lambda _c=False, f=fmt: self.copy_as_requested.emit(tile.filename, f))
        menu.addAction("Expand", lambda: self.expand_requested.emit(tile.filename))
        self._popup(menu, tile.mapToGlobal(pos))

    def _popup(self, menu: QMenu, where) -> None:
        menu.exec(where)


class _Tile(QToolButton):
    double_clicked = Signal(str)

    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.filename:
                self.double_clicked.emit(self.filename)
            return
        super().mouseDoubleClickEvent(event)
