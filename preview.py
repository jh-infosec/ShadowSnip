"""The window that appears after a snip.

The snip is already on the clipboard and already written to disk by the time
this opens, so every control here is optional: save a permanent copy, copy it
again, or take another snip.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import config
import storage
from annotate import AnnotCanvas, AnnotToolbar
from labsnips import LOCKED_STYLE, ClickToEditLine, LabSnipsPanel

# How long after the last mark the edited snip is saved, in milliseconds.
EDIT_SAVE_MS = 500

STYLE = """
QWidget#Root { background: #1b1b1f; }
QLabel { color: #e6e6ec; }
QLabel#Status { color: #9a9aa6; font-size: 11px; }
QLabel#Version { color: #5f5f6b; font-size: 11px; }
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
/* Save changes with nothing to save: clearly not a live button. */
QPushButton#Primary:disabled { background: #1c2533; border-color: #26344a; color: #6c7a8c; }
/* Settings is not one of the snip actions, so it does not look like one.
   A muted violet reads as a different kind of control while staying quieter
   than the blue on New snip -- it should be findable, not competing. */
QPushButton#Settings { background: #3b3550; border-color: #4d4470; }
QPushButton#Settings:hover { background: #474060; }
QPushButton#Settings:pressed { background: #322d45; }
/* A running lab is saving every snip somewhere new, so the button that
   controls it says so from across the room. Amber, because green already
   means "toggle on" (Snip list, Attach) and red means Remove. */
QPushButton[labActive="true"] {
    background: #8a5a0f; border-color: #c98a1e; color: #fff4e0;
    font-weight: 600;
}
QPushButton[labActive="true"]:hover { background: #9c6813; }
QPushButton[labActive="true"]:pressed { background: #744b0c; }
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
/* The selected row is drawn by labsnips.OutlinedTree: a blue edge, not a
   solid fill. The item itself stays transparent so the edge reads. */
QTreeWidget { outline: 0; }
QTreeWidget::item:selected { background: transparent; color: #ffffff; }
QTreeWidget::item:hover { background: rgba(47, 140, 255, 18); }
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
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #1f1f25; color: #9a9aa6; padding: 5px 14px;
    border: 1px solid #2c2c33; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #2a2a31; color: #e6e6ec; border-color: #3a3a44; }
QTabBar::tab:hover:!selected { color: #e6e6ec; }
QTextBrowser {
    background: #15151a; color: #e6e6ec; border: 1px solid #2c2c33;
    border-radius: 4px; padding: 8px;
}
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
    # The Snip list button: show (True) or hide (False) the lab snip list.
    snip_list_toggled = Signal(bool)
    # From the outline: (entry key, section, key to go before or "").
    lab_entry_move_requested = Signal(str, str, str)
    lab_md_open_requested = Signal()
    # The snip on screen was marked up: the edited image, to save everywhere.
    snip_edited = Signal(QImage)
    # Pen and highlighter colours and widths, the redact mode.
    annotation_prefs_changed = Signal(dict)

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
        self._edit_pending = False
        self.setObjectName("Root")
        self.setWindowTitle("ShadowSnip")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setStyleSheet(STYLE)
        self.resize(1100, 760)

        # The snip, and the tools to mark it up. See annotate.py.
        self.canvas = AnnotCanvas()
        self.tools = AnnotToolbar()
        # Always shown, so the tools are there to find from the first launch;
        # greyed out until a snip is on screen to use them on.
        self.tools.set_available(False)
        self.tools.tool_changed.connect(self.canvas.set_tool)
        self.tools.undo_requested.connect(self.canvas.undo)
        self.tools.prefs_changed.connect(self._on_annotation_prefs)
        self.canvas.undo_changed.connect(self.tools.set_undo_enabled)
        self.canvas.edited.connect(self._on_canvas_edited)
        self.canvas.save_as_requested.connect(self.save_as)
        self.canvas.copy_requested.connect(self.copy_again)
        # Edits are saved a moment after the last one, not on every stroke:
        # each save re-encodes the snip and rewrites up to four files.
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(EDIT_SAVE_MS)
        self._edit_timer.timeout.connect(self.flush_edits)
        image_pane = QWidget()
        image_layout = QVBoxLayout(image_pane)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(6)
        image_layout.addWidget(self.tools)
        image_layout.addWidget(self.canvas, 1)

        # The caption for the snip on screen, shown while a lab is engaged.
        # Locked until double-clicked, so a stray click cannot change it, and
        # hovering shows the whole caption when it is too long for the box.
        self.caption = ClickToEditLine("Caption for the lab index - double-click to write one")
        self.caption.setStyleSheet(LOCKED_STYLE)
        self.caption.setVisible(False)
        self.caption.returnPressed.connect(self._save_caption)
        self.caption.editingFinished.connect(self._save_caption)
        self._caption_saved = ""

        self.lab_panel = self._build_lab_panel()
        self.lab_panel.setVisible(False)

        self.snips_panel = LabSnipsPanel()
        self.snips_panel.setVisible(False)
        self.snips_panel.remove_requested.connect(self.snip_remove_requested.emit)
        self.snips_panel.open_requested.connect(self.snip_open_requested.emit)
        self.snips_panel.move_requested.connect(self.lab_entry_move_requested.emit)
        self.snips_panel.open_md_requested.connect(self.lab_md_open_requested.emit)
        # Short names for the parts other code and the tests reach for.
        self.snips_list = self.snips_panel.list
        self.snips_title = self.snips_panel.title
        self.btn_remove_snip = self.snips_panel.btn_remove
        self.btn_open_snip = self.snips_panel.btn_open

        # The image and, during a lab, the list of what is in it side by side.
        # A splitter so the list can be dragged wider when the captions are
        # long, or narrower when the snip needs the room.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.addWidget(image_pane)
        self.splitter.addWidget(self.snips_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([560, 340])

        self.status = QLabel()
        self.status.setObjectName("Status")

        self.btn_new = QPushButton("New snip")
        self.btn_new.setObjectName("Primary")
        self.btn_lab = QPushButton("Start lab")
        # Only shown while a lab runs, since that is the only time there is a
        # list to show. Checked means the list is showing.
        self.btn_snips = QPushButton("Snip list")
        self.btn_snips.setCheckable(True)
        self.btn_snips.setChecked(True)
        self.btn_snips.setVisible(False)
        self.btn_snips.setToolTip(
            "Show or hide the list of this lab's snips beside the image"
        )
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
        self.btn_snips.toggled.connect(self._on_snips_toggled)
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
        bar.addWidget(self.btn_snips)
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
        # The version sits bottom-right, out of the way of the status text but
        # always there when you need to say which build you are running.
        self.version = QLabel(f"ShadowSnip v{config.APP_VERSION}")
        self.version.setObjectName("Version")
        self.version.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.status, 1)
        footer.addWidget(self.version)
        layout.addLayout(footer)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save_as)
        QShortcut(QKeySequence.StandardKey.Copy, self, self.copy_again)
        # Esc puts a tool down first; with nothing in hand it closes the window.
        QShortcut(QKeySequence("Esc"), self, self._on_escape)
        # Ctrl+Enter files the note without reaching for the mouse. Scoped to
        # the window rather than the box, so it works wherever focus happens
        # to be after a snip.
        QShortcut(QKeySequence("Ctrl+Return"), self, self._emit_note)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._emit_note)
        # Ctrl+Z undoes the last mark on the snip. A text box with focus keeps
        # its own Ctrl+Z, because Qt lets the focused editor claim the key.
        QShortcut(QKeySequence.StandardKey.Undo, self, self.canvas.undo)

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

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
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
        self._caption_saved = ""
        self.caption.set_locked(True)
        self.note_edit.clear()
        self.attach_lab(folder_path, caption_cb)
        self._edit_timer.stop()
        self.canvas.load(image)
        # A new snip starts with no tool in hand, so a stray click cannot
        # draw on it.
        self.tools.select(None)
        self.tools.set_available(True)

        self.status.setText(status)
        self._bring_up()

    # -- marking up the snip -------------------------------------------------
    def _on_canvas_edited(self) -> None:
        self._edit_pending = True
        self._edit_timer.start()

    def flush_edits(self) -> bool:
        """Hand any unsaved mark-up to the application now. True if there was some.

        Called after a pause in editing, and before anything that would
        replace or hide the snip (a new snip, closing the window), so an edit
        is never lost or, worse, saved onto the next snip.
        """
        if not self._edit_timer.isActive() and not self._edit_pending:
            return False
        self._edit_timer.stop()
        self._edit_pending = False
        image = self.canvas.image()
        if image is None:
            return False
        self.snip_edited.emit(image)
        return True

    def _on_escape(self) -> None:
        if self.tools.tool is not None:
            self.tools.select(None)
            return
        self.close()

    def set_annotation_prefs(self, prefs: dict) -> None:
        self.tools.set_prefs(prefs)
        self.canvas.prefs = dict(self.tools.prefs)

    def _on_annotation_prefs(self, prefs: dict) -> None:
        self.canvas.prefs = dict(prefs)
        self.annotation_prefs_changed.emit(dict(prefs))

    def set_disk_bytes(self, data: bytes, ext: str) -> None:
        """What Save as writes, after an edit replaced the snip."""
        self._disk_bytes = data
        self._disk_ext = ext

    def open_window(self) -> None:
        """Bring the window up from a tray click, with or without a snip yet."""
        if self._image is None:
            self.canvas.set_message("No snip yet - press the hotkey or New snip")
            if not self.status.text():
                self.status.setText("Ready")
        self._bring_up()

    def _bring_up(self) -> None:
        """Show the window restored, on a screen, in front.

        Used after a snip and for a tray click or relaunch alike. Before
        0.7.4 the snip path skipped the placement, so on a machine with a
        second, differently scaled screen (a TV at 300% beside a laptop) the
        window could open off every screen or as a minimised strip above the
        taskbar: the hotkey snipped, the clipboard filled, and no window.
        """
        first_open = not self.isVisible()
        if self.isMinimized() or self.windowState() & Qt.WindowState.WindowMinimized:
            # show() and raise_() leave a minimised window minimised, so a
            # tray click or a second launch appeared to do nothing at all.
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            self.showNormal()
        self.show()
        if first_open or not self._on_a_screen():
            # After show(), since frameGeometry is only meaningful once the
            # window has been laid out.
            self.center_on_cursor_screen()
        self.raise_()
        self.activateWindow()

    def _on_a_screen(self) -> bool:
        """True when the title bar is on some screen, so the window can be grabbed."""
        frame = self.frameGeometry()
        title = frame.adjusted(0, 0, 0, -(frame.height() - 40))
        for screen in QGuiApplication.screens():
            overlap = screen.availableGeometry().intersected(title)
            if overlap.width() >= min(200, frame.width()) and overlap.height() >= 20:
                return True
        return False

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

    def _emit_note(self) -> None:
        if not self.lab_panel.isVisible():
            return
        text = self.note_edit.toPlainText().strip()
        if not text:
            return
        attach = self.attach_note.isChecked() and self._image is not None
        self.note_added.emit(text, attach)

    def _emit_section(self) -> None:
        text = self.section_edit.currentText().strip()
        if text == self._section_text:
            # editingFinished also fires on focus loss, and re-filing the same
            # breadcrumb every time the box is tabbed away from would rewrite
            # lab.json for nothing.
            return
        self.section_changed.emit(text)

    # -- the lab's snip list -------------------------------------------------
    def set_snips_visible(self, lab_running: bool, shown: bool = True) -> None:
        """Offer the Snip list button during a lab, and show the list if it is on."""
        self.btn_snips.setVisible(lab_running)
        blocked = self.btn_snips.blockSignals(True)
        try:
            self.btn_snips.setChecked(shown)
        finally:
            self.btn_snips.blockSignals(blocked)
        self.snips_panel.setVisible(lab_running and shown)
        if not lab_running:
            self.snips_panel.clear()

    def snips_shown(self) -> bool:
        return self.snips_panel.isVisibleTo(self)

    def _on_snips_toggled(self, on: bool) -> None:
        self.snips_panel.setVisible(on and self.btn_snips.isVisibleTo(self))
        self.snip_list_toggled.emit(on)

    def set_lab_snips(self, rows, current_file: str = "") -> None:
        """Fill the lab snip list from lab.snip_rows(). See labsnips.py."""
        self.snips_panel.set_rows(rows, current_file)

    def set_lab_outline(self, data: dict, md_text: str = "", md_folder=None) -> None:
        self.snips_panel.set_outline(data, md_text, md_folder)

    def selected_snip(self) -> str:
        return self.snips_panel.selected()

    def _emit_remove(self) -> None:
        self.snips_panel._emit_remove()

    def hide_viewer(self) -> None:
        self.snips_panel.hide_viewer()

    def closeEvent(self, event):
        self.snips_panel.hide_viewer()
        self.flush_edits()
        super().closeEvent(event)

    def forget_snip_on_screen(self) -> None:
        """The snip on screen was removed from the lab: stop offering lab actions for it."""
        self.snips_panel.set_current("")
        self._caption_cb = None
        self.caption.clear()
        self.caption.setVisible(False)
        self.attach_note.setEnabled(False)
        self.btn_move_snip.setEnabled(False)

    # -- lab state ---------------------------------------------------------
    def set_lab_name(self, name: str) -> None:
        """Reflect the engaged lab on the toolbar button, text and colour."""
        # Long lab names are cut so the toolbar keeps its shape; the tooltip
        # carries the full name.
        short = name if len(name) <= 22 else name[:21] + "\u2026"
        self.btn_lab.setText(f"\u25cf Stop lab: {short}" if name else "Start lab")
        self.btn_lab.setToolTip(
            f"Every snip is also being filed into lab '{name}'. Click to stop."
            if name
            else "Name a lab; every snip after that is also filed into it"
        )
        active = bool(name)
        if self.btn_lab.property("labActive") != active:
            self.btn_lab.setProperty("labActive", active)
            # A dynamic property only changes the look once the style is
            # re-applied to the widget.
            self.btn_lab.style().unpolish(self.btn_lab)
            self.btn_lab.style().polish(self.btn_lab)
            self.btn_lab.update()

    def lab_running(self) -> bool:
        return bool(self.btn_lab.property("labActive"))

    def attach_lab(self, folder_path: Path | None, caption_cb=None) -> None:
        """Point the folder button and the caption box at a lab, or clear them."""
        self._caption_cb = caption_cb
        self.caption.setVisible(caption_cb is not None)
        if caption_cb is None:
            self.caption.clear()
            self._caption_saved = ""
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
        # Unsaved mark-up first, so Save as writes the snip as it looks now.
        self.flush_edits()
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
        self.flush_edits()
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
        """Write the caption for the snip on screen, when it has changed.

        Runs on Enter and when the box is left. Saving only a change means
        tabbing through the box does not rewrite lab.json, and clearing a
        caption is saved too.
        """
        if self._caption_cb is None:
            return
        text = self.caption.text().strip()
        if text == self._caption_saved:
            return
        try:
            if self._caption_cb(text):
                self._caption_saved = text
                self.status.setText(
                    "Caption written to the lab index" if text else "Caption removed"
                )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.status.setText(f"Caption not saved: {exc}")
        self.caption.set_locked(True)

    def center_on_cursor_screen(self) -> None:
        """Centre on the screen under the pointer, shrunk to fit it if needed.

        The default 1100 x 760 is taller than a laptop screen at 150% or more,
        which put the title bar above the top of the screen.
        """
        screen = QGuiApplication.screenAt(QCursor.pos())
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        extra_w = frame.width() - self.width()
        extra_h = frame.height() - self.height()
        width = min(self.width(), area.width() - extra_w)
        height = min(self.height(), area.height() - extra_h)
        width = max(width, self.minimumWidth())
        height = max(height, self.minimumHeight())
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        # Never above or left of the screen, so the title bar stays reachable.
        frame.moveTop(max(frame.top(), area.top()))
        frame.moveLeft(max(frame.left(), area.left()))
        self.move(frame.topLeft())
