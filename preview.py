"""The window that appears after a snip.

The snip is already on the clipboard and already written to disk by the time
this opens, so every control here is optional: save a permanent copy, copy it
again, or take another snip.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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
QLineEdit {
    background: #232329; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 5px 8px;
}
QPushButton {
    background: #2a2a31; color: #e6e6ec; border: 1px solid #3a3a44;
    border-radius: 4px; padding: 6px 14px;
}
QPushButton:hover { background: #34343d; }
QPushButton:pressed { background: #232329; }
QPushButton#Primary { background: #0a63c4; border-color: #0a63c4; }
QPushButton:checked { background: #1d6b3a; border-color: #2e8b4f; }
QPushButton#Primary:hover { background: #1273da; }
"""


class PreviewWindow(QWidget):
    new_snip_requested = Signal()
    lab_toggle_requested = Signal()
    auto_copy_toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: QImage | None = None
        self._disk_bytes = b""
        self._disk_ext = "png"
        self._latest_path: Path | None = None
        self._folder_path: Path | None = None
        self._copy_again = None
        self._caption_cb = None

        self.setObjectName("Root")
        self.setWindowTitle("ShadowSnip")
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

        self.status = QLabel()
        self.status.setObjectName("Status")

        self.btn_new = QPushButton("New snip")
        self.btn_new.setObjectName("Primary")
        self.btn_lab = QPushButton("Start lab")
        self.btn_auto = QPushButton("Copy on select")
        self.btn_auto.setCheckable(True)
        self.btn_auto.setToolTip(
            "Highlight text anywhere and it is copied without pressing Ctrl+C"
        )
        self.btn_save = QPushButton("Save as...")
        self.btn_copy = QPushButton("Copy again")
        self.btn_folder = QPushButton("Open folder")
        self.btn_close = QPushButton("Close")

        self.btn_new.clicked.connect(self.new_snip_requested.emit)
        self.btn_lab.clicked.connect(self.lab_toggle_requested.emit)
        self.btn_auto.clicked.connect(self.auto_copy_toggled.emit)
        self.btn_save.clicked.connect(self.save_as)
        self.btn_copy.clicked.connect(self.copy_again)
        self.btn_folder.clicked.connect(self.open_folder)
        self.btn_close.clicked.connect(self.close)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_lab)
        bar.addWidget(self.btn_auto)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_copy)
        bar.addWidget(self.btn_folder)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)
        layout.addLayout(bar)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.caption)
        layout.addWidget(self.status)

        QShortcut(QKeySequence.StandardKey.Save, self, self.save_as)
        QShortcut(QKeySequence.StandardKey.Copy, self, self.copy_again)
        QShortcut(QKeySequence("Esc"), self, self.close)

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

    def set_auto_copy(self, on: bool) -> None:
        """Reflect the copy-on-select state without re-emitting the signal."""
        self.btn_auto.setChecked(on)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

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
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())
