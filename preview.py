"""The window that appears after a snip.

The snip is already on the clipboard and already written to disk by the time
this opens, so every control here is optional: save a permanent copy, copy it
again, or take another snip.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import storage

STYLE = """
QWidget#Root { background: #1b1b1f; }
QLabel { color: #e6e6ec; }
QLabel#Status { color: #9a9aa6; font-size: 11px; }
QLabel#Canvas { background: #101013; border: 1px solid #2c2c33; }
QLineEdit, QPlainTextEdit, QComboBox {
    background: #232329; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 5px 8px;
}
QComboBox QAbstractItemView {
    background: #232329; color: #e6e6ec; border: 1px solid #3a3a44;
    selection-background-color: #0a63c4;
}
QLabel#FieldLabel { color: #9a9aa6; font-size: 11px; }
QPushButton {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 6px 14px;
}
QPushButton:hover { background: #34343d; }
QPushButton:pressed { background: #232329; }
QPushButton#Primary { background: #0a63c4; border-color: #0a63c4; }
QPushButton:checked { background: #1d6b3a; border-color: #2e8b4f; }
QPushButton#Primary:hover { background: #1273da; }
/* Settings is not one of the snip actions, so it does not look like one.
   A muted violet reads as a different kind of control while staying quieter
   than the blue on New snip -- it should be findable, not competing. */
QPushButton#Settings { background: #3b3550; border-color: #4d4470; }
QPushButton#Settings:hover { background: #474060; }
QPushButton#Settings:pressed { background: #322d45; }
/* Remove takes a snip out of the lab, so it is the one button that looks
   like it costs something. */
QPushButton#Danger { background: #4a2328; border-color: #6e2f37; }
QPushButton#Danger:hover { background: #5a2a31; }
QPushButton#Danger:disabled, QPushButton:disabled { color: #6c6c78; }
QTreeWidget {
    background: #15151a; color: #e6e6ec; border: 1px solid #2c2c33;
    alternate-background-color: #1a1a20;
}
QTreeWidget::item { padding: 3px 0; }
QTreeWidget::item:selected { background: #0a63c4; color: #ffffff; }
QLabel#SnipDetail {
    background: #15151a; border: 1px solid #2c2c33; border-radius: 4px;
    padding: 6px 8px; color: #c8c8d2;
}
QScrollBar:vertical, QScrollBar:horizontal { background: #15151a; border: none; }
QScrollBar:vertical { width: 10px; }
QScrollBar:horizontal { height: 10px; }
QScrollBar::handle { background: #3a3a44; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QHeaderView::section {
    background: #232329; color: #9a9aa6; border: none;
    border-right: 1px solid #2c2c33; padding: 4px 6px;
}
QSplitter::handle { background: #2c2c33; }
"""


class PreviewWindow(QWidget):
    new_snip_requested = Signal()
    lab_toggle_requested = Signal()
    auto_copy_toggled = Signal()
    # The breadcrumb the lab should file things under from now on.
    section_changed = Signal(str)
    # (text, attach_to_the_snip_on_screen)
    note_added = Signal(str, bool)
    # Re-file the snip on screen under the current section.
    snip_move_requested = Signal()
    settings_requested = Signal()
    # A lab filename: take it out of the lab.
    snip_remove_requested = Signal(str)
    # A lab filename: open the image.
    snip_open_requested = Signal(str)

    def __init__(self, parent=None, icon: QIcon | None = None):
        super().__init__(parent)
        self._image: QImage | None = None
        self._disk_bytes = b""
        self._disk_ext = "png"
        self._latest_path: Path | None = None
        self._folder_path: Path | None = None
        self._copy_again = None
        self._caption_cb = None
        self._section_text = ""
        self._current_lab_file = ""

        self.setObjectName("Root")
        self.setWindowTitle("ShadowSnip")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(STYLE)
        self.resize(1040, 680)

        self.canvas = QLabel()
        self.canvas.setObjectName("Canvas")
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumSize(QSize(320, 200))

        # Only shown while a lab is engaged. What is typed here goes into the
        # lab index next to this snip.
        self.caption = QLineEdit()
        self.caption.setPlaceholderText("Caption for the lab index (optional)")
        self.caption.setVisible(False)
        self.caption.returnPressed.connect(self._save_caption)
        self.caption.editingFinished.connect(self._save_caption)

        self.lab_panel = self._build_lab_panel()
        self.lab_panel.setVisible(False)

        self.snips_panel = self._build_snips_panel()
        self.snips_panel.setVisible(False)

        # The image and, during a lab, the list of what is in it side by side.
        # A splitter so the list can be dragged wider when the captions are
        # long, or narrower when the snip needs the room.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.canvas)
        self.splitter.addWidget(self.snips_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([560, 340])

        self.status = QLabel()
        self.status.setObjectName("Status")

        self.btn_new = QPushButton("New snip")
        self.btn_new.setObjectName("Primary")
        self.btn_lab = QPushButton("Start lab")
        self.btn_auto = QPushButton("Copy on select")
        self.btn_auto.setCheckable(True)
        self.btn_auto.setToolTip(
            "Highlight text, or double-click a word, and it is copied without "
            "pressing Ctrl+C"
        )
        self.btn_save = QPushButton("Save as...")
        self.btn_copy = QPushButton("Copy again")
        self.btn_folder = QPushButton("Open folder")
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setObjectName("Settings")
        self.btn_settings.setToolTip(
            "Hotkeys, save folder, image quality, copy on select, labs"
        )
        self.btn_close = QPushButton("Close")

        self.btn_new.clicked.connect(self.new_snip_requested.emit)
        self.btn_lab.clicked.connect(self.lab_toggle_requested.emit)
        self.btn_auto.clicked.connect(self.auto_copy_toggled.emit)
        self.btn_save.clicked.connect(self.save_as)
        self.btn_copy.clicked.connect(self.copy_again)
        self.btn_folder.clicked.connect(self.open_folder)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        self.btn_close.clicked.connect(self.close)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_lab)
        bar.addWidget(self.btn_auto)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_copy)
        bar.addWidget(self.btn_folder)
        # Past the stretch, away from the snip actions. The buttons on the left
        # change with what is on screen and whether a lab is running; these two
        # are always in the same place, which is what makes Settings findable
        # without hunting through the tray menu.
        bar.addStretch(1)
        bar.addWidget(self.btn_settings)
        bar.addWidget(self.btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)
        layout.addLayout(bar)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.caption)
        layout.addWidget(self.lab_panel)
        layout.addWidget(self.status)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save_as)
        QShortcut(QKeySequence.StandardKey.Copy, self, self.copy_again)
        QShortcut(QKeySequence("Esc"), self, self.close)
        # Ctrl+Enter files the note without reaching for the mouse. Scoped to
        # the window rather than the box, so it works wherever focus happens
        # to be after a snip.
        QShortcut(QKeySequence("Ctrl+Return"), self, self._emit_note)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._emit_note)

    def _build_lab_panel(self) -> QWidget:
        """The section breadcrumb and the note box, shown only during a lab."""
        panel = QWidget()

        # Editable, and pre-filled with the sections this lab already uses.
        # Typing a breadcrumb from memory is how one section becomes two.
        self.section_edit = QComboBox()
        self.section_edit.setEditable(True)
        self.section_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.section_edit.lineEdit().setPlaceholderText(
            "10.10.10.3 / SMB / anonymous share - everything captured lands here"
        )
        self.section_edit.setToolTip(
            "Where snips and notes are filed from now on. Separate the levels "
            "with /; they become the headings in lab.md. The list holds the "
            "sections this lab already uses."
        )
        self.section_edit.lineEdit().returnPressed.connect(self._emit_section)
        self.section_edit.lineEdit().editingFinished.connect(self._emit_section)
        self.section_edit.activated.connect(lambda _index: self._emit_section())

        self.btn_move_snip = QPushButton("Move snip here")
        self.btn_move_snip.setToolTip(
            "Re-file the snip on screen under the section above - for when it "
            "was taken before the section was set"
        )
        self.btn_move_snip.clicked.connect(self.snip_move_requested.emit)

        section_row = QHBoxLayout()
        section_row.setContentsMargins(0, 0, 0, 0)
        section_label = QLabel("Section")
        section_label.setObjectName("FieldLabel")
        section_row.addWidget(section_label)
        section_row.addWidget(self.section_edit, 1)
        section_row.addWidget(self.btn_move_snip)

        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText(
            "Notes for the writeup. Ctrl+Enter files them."
        )
        self.note_edit.setFixedHeight(72)

        self.btn_note = QPushButton("Add note")
        self.btn_note.clicked.connect(self._emit_note)
        self.attach_note = QPushButton("Attach to this snip")
        self.attach_note.setCheckable(True)
        self.attach_note.setChecked(True)
        self.attach_note.setToolTip(
            "An attached note renders directly under this image in lab.md, "
            "rather than on its own in the section"
        )

        note_buttons = QVBoxLayout()
        note_buttons.setContentsMargins(0, 0, 0, 0)
        note_buttons.addWidget(self.btn_note)
        note_buttons.addWidget(self.attach_note)
        note_buttons.addStretch(1)

        note_row = QHBoxLayout()
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.addWidget(self.note_edit, 1)
        note_row.addLayout(note_buttons)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(section_row)
        layout.addLayout(note_row)
        return panel

    def _build_snips_panel(self) -> QWidget:
        """Every snip in the running lab, newest first, with where it was filed.

        The question this answers is "what did the last snip land as, and did
        the note go with it" -- without leaving the window to open lab.md.
        """
        panel = QWidget()

        self.snips_title = QLabel("Lab snips")
        self.snips_title.setObjectName("FieldLabel")

        self.snips_list = QTreeWidget()
        self.snips_list.setColumnCount(5)
        self.snips_list.setHeaderLabels(["#", "Time", "Section", "Caption", "Notes"])
        self.snips_list.setRootIsDecorated(False)
        self.snips_list.setAlternatingRowColors(True)
        self.snips_list.setUniformRowHeights(True)
        self.snips_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.snips_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.snips_list.header()
        header.setStretchLastSection(True)
        for column in (0, 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.snips_list.setColumnWidth(2, 110)
        self.snips_list.setColumnWidth(3, 110)
        self.snips_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.snips_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.snips_list.itemSelectionChanged.connect(self._sync_snip_buttons)

        # The whole story of the selected snip, since the columns cut long
        # sections and notes short: where it was filed, its caption, and every
        # note attached to it.
        self.snip_detail = QLabel()
        self.snip_detail.setObjectName("SnipDetail")
        self.snip_detail.setWordWrap(True)
        self.snip_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.snip_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.snip_detail.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.snip_detail.setMinimumHeight(64)
        self.snips_list.itemDoubleClicked.connect(
            lambda item, _column: self._emit_open(item)
        )
        # Scoped to the list itself, so Delete in the note or caption box
        # still deletes text rather than asking to remove a snip.
        delete_key = QShortcut(QKeySequence.StandardKey.Delete, self.snips_list)
        delete_key.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_key.activated.connect(self._emit_remove)

        self.btn_open_snip = QPushButton("Open")
        self.btn_open_snip.setToolTip("Open the selected snip's image")
        self.btn_open_snip.clicked.connect(lambda: self._emit_open(None))
        self.btn_remove_snip = QPushButton("Remove from lab")
        self.btn_remove_snip.setObjectName("Danger")
        self.btn_remove_snip.setToolTip(
            "Take the selected snip out of the lab and lab.md. The image is "
            "moved to the lab's removed folder, not deleted. Notes attached "
            "only to it go with it."
        )
        self.btn_remove_snip.clicked.connect(self._emit_remove)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.btn_open_snip)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_remove_snip)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.snips_title)
        layout.addWidget(self.snips_list, 1)
        layout.addWidget(self.snip_detail)
        layout.addLayout(buttons)
        self._sync_snip_buttons()
        return panel

    # -- content -----------------------------------------------------------
    def show_snip(self, image: QImage, disk_bytes: bytes, ext: str,
                  latest_path: Path | None, status: str, copy_again,
                  folder_path: Path | None = None, caption_cb=None) -> None:
        self._image = image
        self._disk_bytes = disk_bytes
        self._disk_ext = ext
        self._latest_path = latest_path
        self._copy_again = copy_again

        self.caption.clear()
        self.note_edit.clear()
        self.attach_lab(folder_path, caption_cb)

        self.status.setText(status)
        self._render()
        if self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
        self.show()
        self.raise_()
        self.activateWindow()

    def _render(self) -> None:
        if self._image is None:
            return
        pixmap = QPixmap.fromImage(self._image)
        area = self.canvas.size()
        if pixmap.width() > area.width() or pixmap.height() > area.height():
            pixmap = pixmap.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.canvas.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def open_window(self) -> None:
        """Bring the window up from a tray click, with or without a snip yet."""
        if self._image is None:
            self.canvas.setText("No snip yet - press the hotkey or New snip")
            if not self.status.text():
                self.status.setText("Ready")
        first_open = not self.isVisible()
        if self.isMinimized():
            # show() and raise_() leave a minimised window minimised, so a
            # tray click or a second launch appeared to do nothing at all.
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
        self.show()
        if first_open:
            # Centre after show(), since frameGeometry is only meaningful once
            # the window has been laid out.
            self.center_on_cursor_screen()
        self.raise_()
        self.activateWindow()

    def set_auto_copy(self, on: bool) -> None:
        """Reflect the copy-on-select state without re-emitting the signal."""
        self.btn_auto.setChecked(on)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    # -- sections and notes -------------------------------------------------
    def set_notes_visible(self, visible: bool) -> None:
        """Show the section and note controls. Only meaningful during a lab."""
        self.lab_panel.setVisible(visible)
        if not visible:
            self.note_edit.clear()

    def set_sections(self, paths) -> None:
        """Offer the breadcrumbs this lab already uses, keeping what is typed."""
        typed = self.section_edit.currentText()
        blocked = self.section_edit.blockSignals(True)
        try:
            self.section_edit.clear()  # also empties the line edit
            self.section_edit.addItems(list(paths))
            self.section_edit.setCurrentText(typed)
        finally:
            self.section_edit.blockSignals(blocked)

    def set_section_text(self, text: str) -> None:
        """Reflect the lab's current section, normalised, without re-emitting."""
        self._section_text = text
        if self.section_edit.currentText() != text:
            # setCurrentText writes to the line edit, which emits textChanged
            # but not editingFinished, so this cannot bounce back out through
            # _emit_section.
            self.section_edit.setCurrentText(text)

    def clear_note(self) -> None:
        self.note_edit.clear()

    def _emit_section(self) -> None:
        text = self.section_edit.currentText().strip()
        if text == self._section_text:
            # editingFinished also fires on focus loss, and re-filing the same
            # breadcrumb every time the box is tabbed away from would rewrite
            # lab.json for nothing.
            return
        self.section_changed.emit(text)

    def _emit_note(self) -> None:
        if not self.lab_panel.isVisible():
            return
        text = self.note_edit.toPlainText().strip()
        if not text:
            return
        attach = self.attach_note.isChecked() and self._image is not None
        self.note_added.emit(text, attach)

    # -- the lab's snip list -------------------------------------------------
    def set_snips_visible(self, visible: bool) -> None:
        self.snips_panel.setVisible(visible)
        if not visible:
            self.snips_list.clear()
            self._sync_snip_buttons()

    def set_lab_snips(self, rows, current_file: str = "") -> None:
        """Fill the list from lab.snip_rows(), newest first.

        The snip on screen is marked and selected, so Remove acts on what you
        are looking at unless you pick something else. With nothing on screen
        the newest is selected instead: the wrong snip is nearly always the
        last one.
        """
        # A refresh for a caption or a note keeps whatever you had selected. A
        # new snip on screen takes the selection, so Remove is aimed at it.
        same_snip = (current_file or "") == self._current_lab_file
        previous = self.selected_snip() if same_snip else ""
        self._current_lab_file = current_file or ""
        rows = list(rows)

        self.snips_list.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for row in reversed(rows):
            items[row["file"]] = self._snip_item(row)
            self.snips_list.addTopLevelItem(items[row["file"]])

        count = len(rows)
        self.snips_title.setText(
            f"Lab snips ({count})" if count else "Lab snips - none yet"
        )

        choose = None
        if previous in items:
            choose = items[previous]
        elif self._current_lab_file in items:
            choose = items[self._current_lab_file]
        elif self.snips_list.topLevelItemCount():
            choose = self.snips_list.topLevelItem(0)
        if choose is not None:
            self.snips_list.setCurrentItem(choose)
            self.snips_list.scrollToItem(choose)
        self._sync_snip_buttons()

    def _snip_item(self, row: dict) -> QTreeWidgetItem:
        number = row.get("number", 0)
        label = f"{number:03d}" if isinstance(number, int) else str(number)
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
        item = QTreeWidgetItem(
            [label, clock, section, row.get("caption", ""), note_text]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, row["file"])

        tip = [row["file"], f"Section: {section}"]
        if when:
            tip.append(f"Taken: {when}")
        if row.get("caption"):
            tip.append(f"Caption: {row['caption']}")
        for text in notes:
            tip.append(f"Note: {text}")
        if not notes:
            tip.append("No notes attached")
        tooltip = "\n".join(tip)
        item.setData(1, Qt.ItemDataRole.UserRole, self._detail_text(row, label, section, when, notes))
        for column in range(item.columnCount()):
            item.setToolTip(column, tooltip)

        if row["file"] == self._current_lab_file:
            font = item.font(0)
            font.setBold(True)
            for column in range(item.columnCount()):
                item.setFont(column, font)
            item.setText(0, f"{label} *")
            item.setToolTip(0, tooltip + "\n(on screen now)")
        return item

    @staticmethod
    def _detail_text(row, label, section, when, notes) -> str:
        lines = [f"{label}  {row['file']}"]
        lines.append(f"Filed under: {section}")
        lines.append(f"Caption: {row['caption']}" if row.get("caption") else "No caption")
        if notes:
            for text in notes:
                lines.append(f"Note: {' / '.join(part.strip() for part in text.splitlines() if part.strip())}")
        else:
            lines.append("No notes attached")
        return "\n".join(lines)

    def selected_snip(self) -> str:
        item = self.snips_list.currentItem()
        if item is None or not item.isSelected():
            return ""
        return str(item.data(0, Qt.ItemDataRole.UserRole) or "")

    def _sync_snip_buttons(self) -> None:
        chosen = bool(self.selected_snip())
        self.btn_remove_snip.setEnabled(chosen)
        self.btn_open_snip.setEnabled(chosen)
        item = self.snips_list.currentItem()
        if chosen and item is not None:
            text = str(item.data(1, Qt.ItemDataRole.UserRole) or "")
            if item.data(0, Qt.ItemDataRole.UserRole) == self._current_lab_file:
                text += "\n(the snip on screen)"
            self.snip_detail.setText(text)
        elif self.snips_list.topLevelItemCount():
            self.snip_detail.setText("Select a snip to see how it was filed.")
        else:
            self.snip_detail.setText(
                "Snips taken while this lab runs are listed here, newest first."
            )

    def _emit_remove(self) -> None:
        filename = self.selected_snip()
        if filename:
            self.snip_remove_requested.emit(filename)

    def _emit_open(self, item) -> None:
        if item is not None:
            filename = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        else:
            filename = self.selected_snip()
        if filename:
            self.snip_open_requested.emit(filename)

    def forget_snip_on_screen(self) -> None:
        """The snip on screen was removed from the lab: stop offering lab actions for it."""
        self._current_lab_file = ""
        self._caption_cb = None
        self.caption.clear()
        self.caption.setVisible(False)
        self.attach_note.setEnabled(False)
        self.btn_move_snip.setEnabled(False)

    # -- lab state ---------------------------------------------------------
    def set_lab_name(self, name: str) -> None:
        """Reflect the engaged lab on the toolbar button."""
        self.btn_lab.setText(f"Stop lab ({name})" if name else "Start lab")

    def attach_lab(self, folder_path: Path | None, caption_cb=None) -> None:
        """Point the folder button and the caption box at a lab, or clear them."""
        self._caption_cb = caption_cb
        self.caption.setVisible(caption_cb is not None)
        if caption_cb is None:
            self.caption.clear()
        # Nothing to attach a note to, or to move, until a snip is on screen.
        self.attach_note.setEnabled(self._image is not None)
        self.btn_move_snip.setEnabled(self._image is not None)
        if folder_path is not None:
            self._folder_path = folder_path
            self.btn_folder.setText("Open lab")
        else:
            self._folder_path = (
                self._latest_path.parent if self._latest_path is not None else None
            )
            self.btn_folder.setText("Open folder")

    # -- actions -----------------------------------------------------------
    def save_as(self) -> None:
        if not self._disk_bytes:
            return
        start = storage.suggested_name(self._disk_ext)
        if self._folder_path is not None:
            start = str(self._folder_path / start)
        filters = "PNG image (*.png);;WebP image (*.webp);;JPEG image (*.jpg);;All files (*)"
        path, _ = QFileDialog.getSaveFileName(self, "Save snip", start, filters)
        if not path:
            return
        try:
            storage.write_atomic(Path(path), self._disk_bytes)
        except OSError as exc:
            QMessageBox.warning(self, "ShadowSnip", f"Could not write the file: {exc}")
            return
        self.status.setText(f"Saved to {path}")

    def copy_again(self) -> None:
        if self._copy_again is None:
            return
        try:
            self._copy_again()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.warning(self, "ShadowSnip", f"Could not copy: {exc}")
            return
        self.status.setText("Copied to the clipboard again")

    def open_folder(self) -> None:
        if self._folder_path is None:
            return
        try:
            if self._latest_path is not None and self._folder_path == self._latest_path.parent:
                storage.reveal(self._latest_path)
            else:
                storage.open_folder(self._folder_path)
        except OSError as exc:
            QMessageBox.warning(self, "ShadowSnip", f"Could not open the folder: {exc}")

    def _save_caption(self) -> None:
        if self._caption_cb is None:
            return
        text = self.caption.text().strip()
        if not text:
            return
        try:
            if self._caption_cb(text):
                self.status.setText("Caption written to the lab index")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.status.setText(f"Caption not saved: {exc}")

    def center_on_cursor_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos())
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())
