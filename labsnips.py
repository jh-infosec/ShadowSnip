"""The running lab's snips: list, thumbnails, in-place editing, full-size viewer.

This is the right-hand side of the preview window while a lab runs. It knows
nothing about labs on disk: the application hands it rows from
`lab.snip_rows()` and acts on the signals it emits. That keeps every write to
lab.json in one place (app.py -> lab.py) and lets this module be tested with
plain dictionaries.

## Looking

- Hovering a row shows a larger preview in its tooltip, with how it was filed.
- The selected snip is shown bigger under the list. Clicking that thumbnail,
  **Expand**, double-clicking a row, or Space on the list opens the viewer: the
  snip as large as the screen allows, with Left and Right (or Up and Down)
  cycling through the lab in capture order. The list follows the viewer.

## Editing

The caption and every note attached to the selected snip are editable under
its thumbnail, with a box for adding another note. **Save changes** writes
them. Emptying a note and saving removes that note.

Moving to another snip with unsaved edits saves them first rather than asking.
Typing into a box is already the decision to change it; a dialog on every
arrow key while reviewing would be the wrong trade. The same happens when the
window closes or the lab stops.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImageReader,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyleFactory,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# The glow around the selected row, the same blue as the thumbnail's hover.
SELECT_EDGE = "#2f8cff"
SELECT_FILL = (47, 140, 255, 34)
# The thumbnail of the selected snip, under the list.
DETAIL_THUMB_HEIGHT = 150
# The preview in a row's hover tooltip.
HOVER_BOX = QSize(380, 260)
# How much of the screen the viewer takes.
VIEWER_SCREEN_SHARE = 0.85

STYLE = """
QLabel#SnipThumb {
    background: #101013; border: 1px solid #2c2c33; border-radius: 4px;
}
QLabel#SnipThumb:hover { border: 2px solid #2f8cff; }
QLabel#SnipWhere { color: #9a9aa6; font-size: 11px; }
QScrollArea#NotesScroll { border: none; background: transparent; }
QWidget#NotesInner { background: transparent; }
"""

VIEWER_STYLE = """
QWidget#Viewer { background: #0c0c0f; }
QLabel#ViewerImage { background: #0c0c0f; }
QLabel#ViewerCaption { color: #e6e6ec; font-size: 13px; padding: 8px 12px; }
QLabel#ViewerHint { color: #7c7c88; font-size: 11px; padding: 0 12px 8px 12px; }
QPushButton {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 6px 14px;
}
QPushButton:hover { background: #34343d; }
"""


# -- thumbnails -------------------------------------------------------------
class ThumbCache:
    """Scaled-down copies of lab images, reloaded only when the file changes.

    The list is rebuilt every time the lab folder changes, which during a lab
    is every snip. Decoding every full-size PNG again each time would make the
    list slower the longer the lab runs; decoding each image once, at the size
    it is shown, keeps it flat.
    """

    def __init__(self):
        self._cache: dict[tuple[str, int, int], tuple[int, QPixmap]] = {}

    def get(self, path: str, box: QSize, ratio: float = 1.0) -> QPixmap:
        try:
            stamp = Path(path).stat().st_mtime_ns
        except OSError:
            return QPixmap()
        ratio = max(1.0, float(ratio or 1.0))
        width = max(1, round(box.width() * ratio))
        height = max(1, round(box.height() * ratio))
        key = (path, width, height)
        hit = self._cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]

        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            # Decoding straight to the display size is far cheaper than
            # decoding the whole screenshot and scaling it afterwards.
            reader.setScaledSize(
                size.scaled(QSize(width, height), Qt.AspectRatioMode.KeepAspectRatio)
            )
        image = reader.read()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        if not pixmap.isNull():
            pixmap.setDevicePixelRatio(ratio)
        self._cache[key] = (stamp, pixmap)
        return pixmap

    def keep_only(self, paths) -> None:
        """Forget images no longer in the lab, so the cache cannot grow forever."""
        wanted = set(paths)
        for key in [k for k in self._cache if k[0] not in wanted]:
            del self._cache[key]


def fit_size(path: str, box: QSize) -> QSize:
    """The size an image is shown at inside `box`, from its header alone."""
    size = QImageReader(path).size()
    if not size.isValid() or size.isEmpty():
        return QSize(box)
    if size.width() <= box.width() and size.height() <= box.height():
        return size
    return size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio)


def label_of(row: dict) -> str:
    number = row.get("number", 0)
    return f"{number:03d}" if isinstance(number, int) else str(number)


_FUSION = None


def _shared_fusion():
    """One Fusion style for every list, owned by the application.

    setStyle() does not take ownership. A style owned by Python alone can be
    freed before the widget still drawing with it, which crashes on exit, so
    it is parented to the QApplication and outlives every window.
    """
    global _FUSION
    if _FUSION is None:
        style = QStyleFactory.create("Fusion")
        app = QApplication.instance()
        if style is not None and app is not None:
            style.setParent(app)
        _FUSION = style
    return _FUSION


class OutlinedTree(QTreeWidget):
    """A list whose selected row lights up with a blue edge instead of a fill.

    Two reasons for drawing it by hand. The look: a glowing outline keeps the
    row readable while you arrow through snips, and matches the thumbnail's
    hover. And the colour: the Windows 11 style paints item selection in the
    system accent colour and ignores the stylesheet for it, which is how the
    selection came out red on a machine with a red accent. The list is given
    the Fusion style, which honours the stylesheet, and its highlight colour is
    pinned to the same blue so no platform colour can leak through.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fusion = _shared_fusion()
        if self._fusion is not None:
            self.setStyle(self._fusion)
        palette = self.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            palette.setColor(group, QPalette.ColorRole.Highlight, QColor(*SELECT_FILL))
            palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        self.setPalette(palette)

    def drawRow(self, painter, option, index):
        selected = self.selectionModel() is not None and self.selectionModel().isSelected(index)
        rect = option.rect.adjusted(1, 1, -2, -1)
        if selected:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*SELECT_FILL))
            painter.drawRoundedRect(rect, 4, 4)
            painter.restore()
        super().drawRow(painter, option, index)
        if selected:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor(SELECT_EDGE))
            pen.setWidthF(1.6)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 4, 4)
            painter.restore()


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# -- the full-size viewer -----------------------------------------------------
class SnipViewer(QWidget):
    """A lab snip as large as the screen allows, with arrow keys to cycle.

    A plain window rather than a modal dialog: a modal dialog would block the
    snip hotkey for as long as it was open.
    """

    # The file now shown, so the list can follow.
    current_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("Viewer")
        self.setStyleSheet(VIEWER_STYLE)
        self.setWindowTitle("ShadowSnip - lab snip")
        self._items: list[dict] = []
        self._index = -1
        self._pixmap = QPixmap()

        self.image = QLabel()
        self.image.setObjectName("ViewerImage")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(200, 120)

        self.caption = QLabel()
        self.caption.setObjectName("ViewerCaption")
        self.caption.setWordWrap(True)
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.hint = QLabel("Left / Right for the previous and next snip   |   Esc to close")
        self.hint.setObjectName("ViewerHint")

        self.btn_prev = QPushButton("< Previous")
        self.btn_next = QPushButton("Next >")
        self.btn_close = QPushButton("Close")
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.btn_close.clicked.connect(self.close)
        for button in (self.btn_prev, self.btn_next, self.btn_close):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        bar = QHBoxLayout()
        bar.setContentsMargins(12, 0, 12, 10)
        bar.setSpacing(8)
        bar.addWidget(self.btn_prev)
        bar.addWidget(self.btn_next)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.image, 1)
        layout.addWidget(self.caption)
        layout.addWidget(self.hint)
        layout.addLayout(bar)

        QShortcut(QKeySequence("Esc"), self, self.close)
        for key, step in (("Left", -1), ("Up", -1), ("Right", 1), ("Down", 1)):
            QShortcut(QKeySequence(key), self, lambda s=step: self.step(s))

    # items are in capture order, oldest first, so Right means "later"
    def set_items(self, items: list[dict]) -> None:
        """Replace what can be cycled through, staying on the same snip if it is still there."""
        current = self.current_file()
        self._items = list(items)
        files = [item["file"] for item in self._items]
        if current in files:
            self._index = files.index(current)
            self._show_current(announce=False)
        elif self._items:
            self._index = min(max(self._index, 0), len(self._items) - 1)
            self._show_current(announce=False)
        else:
            self._index = -1
            self.close()

    def show_file(self, filename: str) -> None:
        files = [item["file"] for item in self._items]
        if filename not in files:
            return
        self._index = files.index(filename)
        first = not self.isVisible()
        self._show_current(announce=False)
        if first:
            self._fit_to_screen()
        self.show()
        self.raise_()
        self.activateWindow()

    def current_file(self) -> str:
        if 0 <= self._index < len(self._items):
            return self._items[self._index]["file"]
        return ""

    def step(self, delta: int) -> None:
        if not self._items:
            return
        index = min(max(self._index + delta, 0), len(self._items) - 1)
        if index == self._index:
            return
        self._index = index
        self._show_current(announce=True)

    def _show_current(self, announce: bool) -> None:
        if not (0 <= self._index < len(self._items)):
            return
        item = self._items[self._index]
        self._pixmap = QPixmap(item["path"])
        self._render()
        position = f"{self._index + 1} of {len(self._items)}"
        title = f"{item['label']}  -  {item.get('caption') or 'no caption'}"
        self.caption.setText(f"{title}   ({position})\nFiled under {item.get('section') or 'root'}")
        self.setWindowTitle(f"ShadowSnip - {item['label']} ({position})")
        self.btn_prev.setEnabled(self._index > 0)
        self.btn_next.setEnabled(self._index < len(self._items) - 1)
        if announce:
            self.current_changed.emit(item["file"])

    def _render(self) -> None:
        if self._pixmap.isNull():
            self.image.setText("This image could not be loaded.")
            return
        area = self.image.size()
        pixmap = self._pixmap
        if pixmap.width() > area.width() or pixmap.height() > area.height():
            pixmap = pixmap.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def _fit_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        width = int(area.width() * VIEWER_SCREEN_SHARE)
        height = int(area.height() * VIEWER_SCREEN_SHARE)
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())


# -- the panel ----------------------------------------------------------------
class LabSnipsPanel(QWidget):
    remove_requested = Signal(str)
    open_requested = Signal(str)
    # (file, caption, {note_id: new_text} for changed notes, new_note_text)
    details_saved = Signal(str, str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self._rows: dict[str, dict] = {}
        self._current_lab_file = ""
        self._editing_file = ""
        self._dirty = False
        self._loading = False
        self._note_editors: list[tuple[str, QPlainTextEdit]] = []
        self._thumbs = ThumbCache()
        self.viewer: SnipViewer | None = None

        self.title = QLabel("Lab snips")
        self.title.setObjectName("FieldLabel")

        self.list = OutlinedTree()
        self.list.setColumnCount(5)
        self.list.setHeaderLabels(["#", "Time", "Section", "Caption", "Notes"])
        self.list.setRootIsDecorated(False)
        self.list.setAlternatingRowColors(True)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.list.header()
        header.setStretchLastSection(True)
        for column in (0, 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.list.setColumnWidth(2, 100)
        self.list.setColumnWidth(3, 100)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item, _column: self.expand())

        # Scoped to the list, so these keys still edit text in the boxes below.
        for sequence, slot in (
            (QKeySequence.StandardKey.Delete, self._emit_remove),
            (QKeySequence("Space"), self.expand),
            (QKeySequence("Return"), self.expand),
        ):
            shortcut = QShortcut(sequence, self.list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(slot)

        self.detail = self._build_detail()

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.addWidget(self.list)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        # Inset from the splitter handle beside the image.
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.splitter, 1)
        self._load_editor("")

    def _build_detail(self) -> QWidget:
        panel = QWidget()

        self.thumb = ClickableLabel()
        self.thumb.setObjectName("SnipThumb")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedHeight(DETAIL_THUMB_HEIGHT)
        self.thumb.setMinimumWidth(120)
        self.thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb.setToolTip("Click to expand. Left and Right then cycle through the lab.")
        self.thumb.clicked.connect(self.expand)

        self.where = QLabel()
        self.where.setObjectName("SnipWhere")
        self.where.setTextFormat(Qt.TextFormat.PlainText)
        self.where.setWordWrap(True)
        self.btn_expand = QPushButton("Expand")
        self.btn_expand.setToolTip("Show this snip full size (Space on the list does the same)")
        self.btn_expand.clicked.connect(self.expand)

        where_row = QHBoxLayout()
        where_row.setContentsMargins(0, 0, 0, 0)
        where_row.addWidget(self.where, 1)
        where_row.addWidget(self.btn_expand)

        self.caption_edit = QLineEdit()
        self.caption_edit.setPlaceholderText("Caption for lab.md")
        self.caption_edit.textEdited.connect(self._mark_dirty)
        self.caption_edit.returnPressed.connect(self.save)

        self.notes_inner = QWidget()
        self.notes_inner.setObjectName("NotesInner")
        self.notes_layout = QVBoxLayout(self.notes_inner)
        self.notes_layout.setContentsMargins(0, 0, 0, 0)
        self.notes_layout.setSpacing(6)
        self.new_note = QPlainTextEdit()
        self.new_note.setPlaceholderText("Add a note to this snip")
        self.new_note.setFixedHeight(48)
        self.new_note.textChanged.connect(self._mark_dirty)
        self.notes_layout.addWidget(self.new_note)
        self.notes_layout.addStretch(1)

        self.notes_scroll = QScrollArea()
        self.notes_scroll.setObjectName("NotesScroll")
        self.notes_scroll.setWidgetResizable(True)
        self.notes_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_scroll.setWidget(self.notes_inner)

        self.btn_save = QPushButton("Save changes")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setToolTip(
            "Write the caption and notes into lab.md. Empty a note and save to "
            "remove it. Moving to another snip saves too."
        )
        self.btn_save.clicked.connect(self.save)
        self.btn_open = QPushButton("Open")
        self.btn_open.setToolTip("Open the image in your default viewer")
        self.btn_open.clicked.connect(self._emit_open)
        self.btn_remove = QPushButton("Remove from lab")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.setToolTip(
            "Take the selected snip out of the lab and lab.md. The image is "
            "moved to the lab's removed folder, not deleted. Notes attached "
            "only to it go with it."
        )
        self.btn_remove.clicked.connect(self._emit_remove)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self.btn_save, 1)
        buttons.addWidget(self.btn_open, 1)
        buttons.addWidget(self.btn_remove, 1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.thumb)
        layout.addLayout(where_row)
        layout.addWidget(self.caption_edit)
        layout.addWidget(self.notes_scroll, 1)
        layout.addLayout(buttons)
        return panel

    # -- filling ------------------------------------------------------------
    def set_rows(self, rows, current_file: str = "") -> None:
        """Fill from lab.snip_rows(), newest first.

        A refresh for the same snip keeps whatever you had selected, and any
        edits in progress. A new snip on screen takes the selection, so the
        buttons act on what you are looking at.
        """
        same_snip = (current_file or "") == self._current_lab_file
        previous = self.selected() if same_snip else ""
        self._current_lab_file = current_file or ""
        rows = list(rows)
        self._rows = {row["file"]: row for row in rows}

        blocked = self.list.blockSignals(True)
        try:
            self.list.clear()
            items: dict[str, QTreeWidgetItem] = {}
            for row in reversed(rows):
                items[row["file"]] = self._item_for(row)
                self.list.addTopLevelItem(items[row["file"]])

            choose = None
            if previous in items:
                choose = items[previous]
            elif self._current_lab_file in items:
                choose = items[self._current_lab_file]
            elif self.list.topLevelItemCount():
                choose = self.list.topLevelItem(0)
            if choose is not None:
                self.list.setCurrentItem(choose)
                self.list.scrollToItem(choose)
        finally:
            self.list.blockSignals(blocked)

        count = len(rows)
        self.title.setText(f"Lab snips ({count})" if count else "Lab snips - none yet")
        self._thumbs.keep_only(row.get("path", "") for row in rows)

        selected = self.selected()
        if self._dirty and self._editing_file and selected != self._editing_file:
            # The snip being edited was replaced by a newer one on screen. Keep
            # the words: save them against the snip they were typed for.
            self.flush()
        if selected == self._editing_file and self._dirty:
            self._refresh_detail_view(selected)
        else:
            self._load_editor(selected)
        if self.viewer is not None:
            self.viewer.set_items(self._viewer_items())

    def set_current(self, filename: str) -> None:
        """Mark a different snip (or none) as the one on screen."""
        self._current_lab_file = filename or ""

    def clear(self) -> None:
        self.flush()
        self._rows = {}
        self.list.clear()
        self._load_editor("")
        if self.viewer is not None:
            self.viewer.close()

    def _item_for(self, row: dict) -> QTreeWidgetItem:
        label = label_of(row)
        when = str(row.get("time", ""))
        clock = when.split(" ", 1)[1] if " " in when else when
        notes = [str(text) for text in row.get("notes", ()) if str(text).strip()]
        if not notes:
            note_text = ""
        elif len(notes) == 1:
            note_text = notes[0].splitlines()[0]
        else:
            note_text = f"({len(notes)}) {notes[0].splitlines()[0]}"
        section = row.get("section", "") or "root"
        on_screen = row["file"] == self._current_lab_file

        item = QTreeWidgetItem(
            [f"{label} *" if on_screen else label, clock, section,
             row.get("caption", ""), note_text]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, row["file"])

        tooltip = self._hover_html(row, label, section, when, notes, on_screen)
        for column in range(item.columnCount()):
            item.setToolTip(column, tooltip)
        if on_screen:
            font = item.font(0)
            font.setBold(True)
            for column in range(item.columnCount()):
                item.setFont(column, font)
        return item

    @staticmethod
    def _hover_html(row, label, section, when, notes, on_screen) -> str:
        """The row tooltip: a large preview of the snip, then how it was filed."""
        parts = []
        path = row.get("path", "")
        if path and Path(path).is_file():
            size = fit_size(path, HOVER_BOX)
            source = html.escape(QUrl.fromLocalFile(path).toString(), quote=True)
            parts.append(
                f'<img src="{source}" width="{size.width()}" height="{size.height()}">'
            )
        lines = [f"<b>{html.escape(label)}</b>  {html.escape(row['file'])}"]
        lines.append(f"Filed under: {html.escape(section)}")
        if when:
            lines.append(f"Taken: {html.escape(when)}")
        caption = row.get("caption", "")
        lines.append(f"Caption: {html.escape(caption)}" if caption else "No caption")
        for text in notes:
            lines.append(f"Note: {html.escape(text)}".replace("\n", "<br>"))
        if not notes:
            lines.append("No notes attached")
        if on_screen:
            lines.append("<i>On screen now</i>")
        parts.append("<br>".join(lines))
        return "<br>".join(parts)

    # -- selection and the editor ---------------------------------------------
    def selected(self) -> str:
        item = self.list.currentItem()
        if item is None or not item.isSelected():
            return ""
        return str(item.data(0, Qt.ItemDataRole.UserRole) or "")

    def select(self, filename: str) -> None:
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == filename:
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item)
                return

    def _on_selection_changed(self) -> None:
        selected = self.selected()
        if self._dirty and self._editing_file and selected != self._editing_file:
            self.flush()
        self._load_editor(selected)

    def _load_editor(self, filename: str) -> None:
        row = self._rows.get(filename)
        self._loading = True
        try:
            for _note_id, editor in self._note_editors:
                self.notes_layout.removeWidget(editor)
                editor.deleteLater()
            self._note_editors = []
            self.new_note.clear()

            if row is None:
                self._editing_file = ""
                self.thumb.clear()
                self.thumb.setText(
                    "Snips taken while this lab runs are listed above, newest first."
                    if not self._rows
                    else "Select a snip"
                )
                self.where.setText("")
                self.caption_edit.clear()
                self._set_editable(False, "")
                self._sync_buttons()
                return

            self._editing_file = filename
            self._refresh_detail_view(filename)
            self.caption_edit.setText(row.get("caption", ""))
            for note in row.get("note_entries", []):
                editor = QPlainTextEdit(note.get("text", ""))
                editor.setFixedHeight(52)
                editor.setToolTip(
                    f"Note {note.get('id', '')}. Empty it and save to remove it."
                )
                editor.textChanged.connect(self._mark_dirty)
                # Before the new-note box, which stays last.
                self.notes_layout.insertWidget(len(self._note_editors), editor)
                self._note_editors.append((str(note.get("id", "")), editor))
            recorded = bool(row.get("recorded", True))
            self._set_editable(
                recorded,
                "" if recorded else
                "This snip has no lab record, so it cannot be captioned. "
                "Keep a lab record in Settings to caption and annotate snips.",
            )
        finally:
            self._loading = False
            self._dirty = False
            self._sync_buttons()

    def _refresh_detail_view(self, filename: str) -> None:
        """The thumbnail and the filing line, without touching the edit boxes."""
        row = self._rows.get(filename)
        if row is None:
            return
        size = QSize(max(120, self.thumb.width() - 4), DETAIL_THUMB_HEIGHT - 4)
        pixmap = self._thumbs.get(row.get("path", ""), size, self.devicePixelRatioF())
        if pixmap.isNull():
            self.thumb.setText("Image not found")
        else:
            self.thumb.setPixmap(pixmap)
        when = str(row.get("time", ""))
        where = f"{label_of(row)}  |  {row.get('section') or 'root'}"
        if when:
            where += f"  |  {when}"
        if row["file"] == self._current_lab_file:
            where += "  |  on screen"
        self.where.setText(where)

    def _set_editable(self, editable: bool, reason: str) -> None:
        self.caption_edit.setReadOnly(not editable)
        self.new_note.setReadOnly(not editable)
        for _note_id, editor in self._note_editors:
            editor.setReadOnly(not editable)
        self.caption_edit.setToolTip(reason)
        self.new_note.setPlaceholderText(reason or "Add a note to this snip")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._editing_file:
            self._refresh_detail_view(self._editing_file)

    def _mark_dirty(self, *_args) -> None:
        if self._loading or not self._editing_file:
            return
        self._dirty = True
        self._sync_buttons()

    def is_dirty(self) -> bool:
        return self._dirty

    def _sync_buttons(self) -> None:
        chosen = bool(self.selected())
        self.btn_remove.setEnabled(chosen)
        self.btn_open.setEnabled(chosen)
        self.btn_expand.setEnabled(chosen)
        self.btn_save.setEnabled(self._dirty)
        self.btn_save.setText("Save changes" if self._dirty else "Saved")

    # -- actions ----------------------------------------------------------------
    def save(self) -> None:
        self.flush()

    def flush(self) -> bool:
        """Emit the edits for the snip in the editor, if there are any."""
        if not self._dirty or not self._editing_file:
            return False
        row = self._rows.get(self._editing_file, {})
        original = {
            str(note.get("id", "")): str(note.get("text", ""))
            for note in row.get("note_entries", [])
        }
        changed = {}
        for note_id, editor in self._note_editors:
            text = editor.toPlainText().strip()
            if text != original.get(note_id, "").strip():
                changed[note_id] = text
        caption = self.caption_edit.text().strip()
        new_note = self.new_note.toPlainText().strip()

        # Remember what was saved, so a refresh before the lab has been
        # re-read does not show the old words back.
        if row:
            row["caption"] = caption
            kept = []
            for note in row.get("note_entries", []):
                text = changed.get(str(note.get("id", "")), note.get("text", ""))
                if text:
                    kept.append({"id": note.get("id", ""), "text": text})
            row["note_entries"] = kept
            row["notes"] = [note["text"] for note in kept]

        self._dirty = False
        self._sync_buttons()
        self.details_saved.emit(self._editing_file, caption, changed, new_note)
        if new_note:
            self.new_note.clear()
        return True

    def _viewer_items(self) -> list[dict]:
        items = []
        for row in sorted(self._rows.values(), key=lambda r: (r["number"], r["file"])):
            items.append(
                {
                    "file": row["file"],
                    "path": row.get("path", ""),
                    "label": label_of(row),
                    "caption": row.get("caption", ""),
                    "section": row.get("section", ""),
                }
            )
        return items

    def expand(self) -> None:
        filename = self.selected()
        if not filename:
            return
        if self.viewer is None:
            self.viewer = SnipViewer()
            self.viewer.current_changed.connect(self.select)
        self.viewer.set_items(self._viewer_items())
        self.viewer.show_file(filename)

    def hide_viewer(self) -> None:
        if self.viewer is not None and self.viewer.isVisible():
            self.viewer.close()

    def _emit_remove(self) -> None:
        filename = self.selected()
        if filename:
            self.remove_requested.emit(filename)

    def _emit_open(self) -> None:
        filename = self.selected()
        if filename:
            self.open_requested.emit(filename)
