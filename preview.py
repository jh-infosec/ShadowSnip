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
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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

        self.setObjectName("Root")
        self.setWindowTitle("ShadowSnip")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(STYLE)
        self.resize(900, 640)

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
        layout.addWidget(self.canvas, 1)
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
